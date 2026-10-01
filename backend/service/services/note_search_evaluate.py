"""Synthetic, repeatable local note search acceptance. Never reads user notes."""
import json
import os
import tempfile
import time
from pathlib import Path
import chromadb
from chromadb.config import Settings
from sqlalchemy import create_engine, text
from medical.bge_embedding import BGEEmbedding
from .note_search_index import NoteSearchIndex


FIXTURES = [
 ('差旅费用','出差结束后提交高铁票、酒店发票和审批单，财务统一处理报销。',['高铁票','出差报销需要准备哪些凭证','酒店发票','去外地办事花的钱怎么申请返还']),
 ('项目会议','研发会议决定优先修复登录失败，下周三检查进度，王明负责接口。',['登录失败','谁负责研发的接口工作','王明','系统登不上去的问题何时跟进']),
 ('生活缴费','房租每月五号交给房东李华，水电费月底单独结算。',['房租','租房费用什么时候交','李华','月底需要结算哪些居住费用']),
 ('运动安排','每周二和周四去游泳馆练习自由泳，周末骑自行车。',['自由泳','哪几天安排水上锻炼','自行车','周末计划做什么体育活动']),
 ('读书摘记','读书时先看目录，按章节做摘要，把不理解的问题记在页边。',['页边','如何整理书中的重点','目录','看书遇到不懂的地方怎么记录']),
 ('厨房备忘','做番茄炒蛋先炒鸡蛋盛出，再炒番茄，最后混合。',['番茄炒蛋','西红柿和鸡蛋的烹饪顺序','盛出','下厨时先处理鸡蛋还是番茄']),
 ('宠物照料','猫粮放在储物柜第二层，每天清理猫砂盆，周六梳毛。',['猫砂盆','家里的猫每天需要做哪些清洁','猫粮','宠物食品收在哪里']),
 ('旅行清单','去海边前准备防晒衣、遮阳帽和身份证，提前下载离线地图。',['遮阳帽','海边旅行要带什么','离线地图','出游前要把导航资料保存好吗']),
 ('面试准备','视频面试前测试麦克风和摄像头，准备两分钟自我介绍。',['麦克风','线上应聘前检查哪些设备','自我介绍','求职视频通话需要提前准备什么']),
 ('付款记录','给张三转账500元，备注归还上个月借款，并保存转账凭证。',['张三','之前借的钱还给谁了','500元','还款凭据需要保存吗'])]
NEGATIVES=['量子纠缠实验装置','火星探测器轨道参数','恐龙灭绝年代','硅晶圆光刻工艺','冰川古气候研究','海底火山喷发机制','考古陶器断代方法','黑洞事件视界','珊瑚礁生态修复','核聚变反应堆结构','彗星尾巴组成','中世纪纹章学','地幔矿物相变','数字签名椭圆曲线','极光磁层耦合','古埃及象形文字','深海热泉微生物','质谱仪校准','恒星光谱分类','超导材料临界温度']


def main():
    import torch
    torch.set_num_threads(2)
    model=BGEEmbedding(batch_size=4); model._load()
    with tempfile.TemporaryDirectory() as tmp:
        engine=create_engine('sqlite:///'+str(Path(tmp)/'notes.sqlite'))
        with engine.begin() as c:
            c.execute(text('CREATE TABLE notes(id INTEGER PRIMARY KEY,user_id INTEGER,title TEXT,content TEXT,tag TEXT,status TEXT,last_updated TEXT)'))
        client=chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
        collection=client.create_collection('notes_acceptance',metadata={'hnsw:space':'cosine'})
        index=NoteSearchIndex(engine,model,collection); index.install()
        cases=[]
        for i,(title,body,queries) in enumerate(FIXTURES,1):
            # Long irrelevant introduction deliberately puts the useful fact at the end.
            content=('这是一份日常工作生活记录，具体事项见后文。\n'*55 if i==1 else '')+body
            with engine.begin() as c:
                c.execute(text("INSERT INTO notes VALUES(:id,1,:title,:body,'work','draft','2026-09-29')"),{'id':i,'title':title,'body':content})
            for j,q in enumerate(queries): cases.append({'query':q,'expected':i,'split':'dev' if j<2 else 'validation'})
        for i,q in enumerate(NEGATIVES): cases.append({'query':q,'expected':None,'split':'dev' if i<10 else 'validation'})
        while index.process_one(): pass
        def score(rows):
            positive=[x for x in rows if x['expected']]
            negative=[x for x in rows if not x['expected']]
            return {'recall_at_5':sum(x['expected'] in x['ids'] for x in positive)/len(positive),
                    'negative_rejection':sum(not x['ids'] for x in negative)/len(negative),
                    'p95_ms':sorted(x['ms'] for x in rows)[int(len(rows)*.95)-1]}
        def run(split):
            rows=[]
            for case in cases:
                if case['split']!=split:continue
                started=time.perf_counter(); hits=index.search(1,case['query'],5)
                rows.append({**case,'ids':[h['id'] for h in hits],'ms':round((time.perf_counter()-started)*1000,1)})
            return {'metrics':score(rows),'details':rows}
        report={'scope':'synthetic_developer_cases_not_blind_real_user_eval','cases':len(cases),'candidates':{}}
        for value in (0.35,0.45,0.55):
            os.environ['NOTE_BGE_MAX_DISTANCE']=str(value)
            result=run('dev'); report['candidates'][str(value)]=result
        selected=max(report['candidates'],key=lambda v:report['candidates'][v]['metrics']['recall_at_5']+report['candidates'][v]['metrics']['negative_rejection'])
        os.environ['NOTE_BGE_MAX_DISTANCE']=selected
        report['selected_max_distance']=float(selected)
        report['validation']=run('validation')
        baseline=[]
        with engine.connect() as c:
            for case in cases:
                if case['split']!='validation':continue
                started=time.perf_counter()
                ids=[r[0] for r in c.execute(text('SELECT id FROM notes WHERE user_id=1 AND (title LIKE :q OR content LIKE :q) LIMIT 5'),{'q':'%'+case['query']+'%'})]
                baseline.append({**case,'ids':ids,'ms':round((time.perf_counter()-started)*1000,2)})
        report['keyword_baseline']=score(baseline)
        path=Path('data/note_search_reports/synthetic_v1.json');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'selected':selected,'validation':report['validation']['metrics'],'baseline':report['keyword_baseline'],'report':str(path)}),flush=True)
        index.pool.shutdown(wait=True); engine.dispose()


if __name__=='__main__':main()
