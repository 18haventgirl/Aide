const agentDetails: Record<string, { label: string; description: string }> = {
  'Triage Agent': { label: '任务协调助手', description: '识别需求，安排合适的助手处理。' },
  'Weather Agent': { label: '天气助手', description: '查询天气，整理出行相关信息。' },
  'News Agent': { label: '资讯助手', description: '查找资讯并梳理重点。' },
  'Recipe Agent': { label: '食谱助手', description: '提供菜谱与烹饪建议。' },
  'Personal Assistant Agent': { label: '日常记录助手', description: '协助管理笔记、待办与个人记录。' },
  'Medical Health Agent': { label: '健康知识助手', description: '检索健康资料，整理有来源的参考信息。' },
  'Medical Record Parser Agent': { label: '病历整理助手', description: '从病历原文提取信息，供你逐项核对。' },
  'Conversation Title Agent': { label: '会话整理助手', description: '为对话生成便于查找的标题。' },
};

export function agentLabel(name: string): string {
  return agentDetails[name]?.label ?? name;
}

export function agentDescription(name: string, fallback: string): string {
  return agentDetails[name]?.description ?? fallback;
}
