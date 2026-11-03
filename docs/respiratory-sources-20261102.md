# 成人咳嗽与居家测温资料选段

2026-11-02 取得两篇公开中文科普网页。原始 HTML 和提取段落保存于本机，版本配方保存入库选择、来源信息、SHA256 和每个排除段的理由。资料用于成人健康科普和就医引导的本机研究，临床复核和公开再分发许可待确认。

| 资料 | 原始 HTML | 提取的非空 p 段 | 完整选入段序号（从0起算） |
| --- | ---: | ---: | --- |
| `QJ-COUGH-20241010` | 74,376 字节 | 26 | 15、16、17、18、19 |
| `SZ-TEMPERATURE-20261023` | 35,916 字节 | 25 | 6、7、10、19、20、21 |

先检索了 GitHub 的中文医疗数据项目。华佗项目的作者把来源列为百科、图谱和在线问答，并说明 Lite 数据经过提纯与重写。本批原文定位需要能直接复核的发布页面，因此从卫健委网站单独取得以下两份资料。[Huatuo-26M 项目说明](https://github.com/FreedomIntelligence/Huatuo-26M/blob/main/README_zh.md)

潜江市卫健委页面的发布日期和 `PubDate` 均为 2024-10-10，`ContentSource` 为武汉协和医院、健康湖北。第15段在通常病程之后引出就医提示，第16～19段为完整的四项提示，一并保留，避免将病程时长误用为出现其他警示症状后仍可等待的理由。儿科用药、蜂蜜和未明确病因的缓解建议在本批范围之外。[潜江市政府原文](https://www.hbqj.gov.cn/xxgk/xxgkml/szfxxgkml/qtzdgknr/hygq/202410/t20241021_5378358.html)

深圳市医疗卫生专业服务中心的发布日期为 2026-10-23。选段包括电子体温计接触测量、影响额温读数的因素、异常复测及持续发热就医。第20段还包含水银体温计破损的设备警示，完整保留于原段。查询时适用范围为家用测温和一般观察，成人发热的全面病因判断与处理仍需更多来源。[深圳市卫健委原文](https://wjw.sz.gov.cn/szylws/gzdt/content/post_13037547.html)

另查的西安交通大学第一附属医院夏季发热资料返回 HTTP 412，鄂尔多斯市卫健委转载的国家卫健委感冒/流感发布会资料出现证书校验失败，均未入选。深圳页面首次请求遇到 TLS 连接中断，改用系统 HTTPS 客户端并保留证书校验、通过 7890 代理，取得 200 响应和完整 HTML。[西安医院候选](https://jdyfy.com/info/1321/192061.htm) · [鄂尔多斯市卫健委候选](https://wjw.ordos.gov.cn/ztzlx/jkzs_ztzl/kpzyk/wzkp_kpzyk/202511/t20251124_1287054.html)

## 构建与核验

- 采集文件在 `medical-rag-data/raw/qj-cough-20241010/2026-11-02/` 和 `medical-rag-data/raw/sz-temperature-20261023/2026-11-02/`。每个目录含 `page.html` 和 `extracted-paragraphs.txt`。
- 对应配方为 `medical-rag-data/registry/chinese_respiratory_batch_20261102.json` 和 `medical-rag-data/registry/chinese_thermometry_batch_20261102.json`。两份配方各由 `medical.capture_official_batch` 重放，并将导入包分别写入 `medical-rag-data/staging/respiratory-bundles/2026-11-02/`、`medical-rag-data/staging/thermometry-bundles/2026-11-02/`。
- 再次从原料独立重建后，比较结果与存盘导入包完全一致。两个正文的 SHA256 分别为 `8225006c06909d06c4c25566858573d0ba264e37516327488f00902a7e6bdc46` 和 `3750fbcc16f01c6ab122a4488128e78e7fb1cf6638eeffdd8f678149e9b34592`。逐段来源坐标、选段顺序和全部40个遗漏段对应的理由均已核验。
