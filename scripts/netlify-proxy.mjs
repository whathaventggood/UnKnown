// Build-time only. API_PROXY_ORIGIN is a public service origin, never an API key.
import {writeFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {dirname,resolve} from 'node:path'
export function redirectsFor(raw=''){
 const fallback='/* /index.html 200\n'
 if(!raw.trim())return fallback
 const origin=raw.trim().replace(/\/$/,'')
 const url=new URL(origin)
 if(url.protocol!=='https:'||url.username||url.password||url.pathname!=='/'||url.search||url.hash||url.origin!==origin)throw new Error('API_PROXY_ORIGIN must be an exact public HTTPS origin without credentials/path/query')
 return `/api/* ${origin}/api/:splat 200\n${fallback}`
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 writeFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../frontend/public/_redirects'),redirectsFor(process.env.API_PROXY_ORIGIN||''))
}
