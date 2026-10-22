export type ModuleId = 'diet' | 'tech' | 'finance' | 'aesthetics' | 'plans';
export type Row = { id: string; kind: string; module: string; version: number; data: Record<string, any>; created_at: string; updated_at: string; project_id?: string };
export type Settings = { version: number; timezone: string; timezone_confirmed: boolean; locale: string; reduced_motion: boolean; schedule_enabled: boolean; daily_time: string; evening_enabled: boolean; evening_time: string; weekly_enabled: boolean; public_sources_enabled: boolean; agent_enabled: boolean; onboarding_done: boolean; data_root?: string };
let csrf = '';
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api/v1/' + path, { method, credentials: 'same-origin', headers: { ...(body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(method !== 'GET' ? { 'X-CSRF-Token': csrf } : {}) }, body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body) });
  const value = await response.json();
  if (!response.ok) throw new Error(value.message || `请求失败 (${response.status})`);
  return value as T;
}
export async function initSession() { csrf = (await api('session')).csrf_token; }
export const modules: { id: ModuleId; title: string; en: string; caption: string; color: string }[] = [
  { id: 'diet', title: '饮食健康', en: 'NOURISH', caption: '认真吃饭，好好生活', color: 'green' },
  { id: 'tech', title: '全球科技', en: 'DISCOVER', caption: '与正在发生的未来同行', color: 'blue' },
  { id: 'finance', title: '金融股市', en: 'OBSERVE', caption: '看见趋势，也看清依据', color: 'purple' },
  { id: 'aesthetics', title: '审美设计', en: 'CREATE', caption: '收藏触动你的每个瞬间', color: 'orange' },
  { id: 'plans', title: '短期计划', en: 'FOCUS', caption: '把想做的事，向前推进', color: 'pink' },
];
export const statuses: Record<string, string> = { disabled: '已关闭', todo: '待开始', doing: '进行中', blocked: '有阻塞', done: '已完成', cancelled: '已取消', queued: '排队中', running: '执行中', succeeded: '已完成', partial: '部分完成', failed: '执行失败', awaiting_permission: '等待许可', pending: '待核对', confirmed: '已确认', planned: '计划中', skipped: '未执行', replaced: '已替换', ready: '已连接', unauthenticated: '尚未登录', unconfigured: '未配置', unavailable: '暂不可用', unsupported: '暂不支持' };
export function fmtDate(value?: string, zone = 'Asia/Shanghai') { return value ? new Date(value).toLocaleString('zh-CN', { timeZone: zone, month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '尚未更新'; }
export function safeUrl(value: string) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : '#'; } catch { return '#'; } }
export function jobKey(module: string, operation: string) { return `${module}:${operation}:${crypto.randomUUID()}`; }
