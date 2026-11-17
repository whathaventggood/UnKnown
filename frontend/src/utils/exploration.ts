import {reactive} from 'vue'
import type {Mode} from '../types'

// Only the mode is persisted. Batch credentials and profile data stay off storage.
export function savedMode():Mode {
 try {const mode=sessionStorage.getItem('unknown-explore-mode');if(mode==='bridge'||mode==='broad')return mode} catch {/* storage is optional */}
 return 'unknown'
}
export function saveMode(mode:Mode){try{sessionStorage.setItem('unknown-explore-mode',mode)}catch{/* storage is optional */}}
export const exploration=reactive({scroll:0,pendingRefresh:new Map<Mode,string>()})
export function clearExploration(){exploration.scroll=0;exploration.pendingRefresh.clear();saveMode('unknown')}
