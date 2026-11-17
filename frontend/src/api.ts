export class ApiError extends Error {code:string;requestId?:string;status:number;constructor(message:string,code:string,status:number,requestId?:string){super(message);this.code=code;this.status=status;this.requestId=requestId}}
const API_BASE=(import.meta.env.VITE_API_BASE_URL||'/api').replace(/\/$/,'')
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),path.startsWith('/ai/')&&options.method==='POST'?120000:20000)
 try{
  const response=await fetch(`${API_BASE}${path}`,{credentials:'include',...options,signal:options.signal||controller.signal,headers:{'Content-Type':'application/json',...options.headers}})
  let data;try{data=await response.json()}catch{throw new ApiError('服务暂时没有返回有效数据，请稍后重试。','INVALID_RESPONSE',response.status)}
  if(!response.ok)throw new ApiError(data.error?.message||data.detail||'请求未能完成，请重试。',data.error?.code||'REQUEST_FAILED',response.status,data.error?.request_id)
  return data as T
 }catch(e){if(e instanceof DOMException&&e.name==='AbortError')throw new ApiError('连接等待超时，请稍后重试。','REQUEST_TIMEOUT',408);throw e}finally{clearTimeout(timeout)}
}
export const post=<T>(path:string,body:unknown)=>api<T>(path,{method:'POST',body:JSON.stringify(body)})
export const key=()=>crypto.randomUUID()
export const dateLabel=(s:string)=>new Date(s).toLocaleDateString('zh-CN',{month:'long',day:'numeric'})
export const safeUrl=(url?:string)=>{try{const u=new URL(url||'');return ['https:','http:'].includes(u.protocol)?u.href:'#'}catch{return '#'}}
