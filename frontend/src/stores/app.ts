import {defineStore} from 'pinia'
import {ref} from 'vue'
import {api} from '../api'
import type {Discipline,Profile} from '../types'
export const useApp=defineStore('app',()=>{const profile=ref<Profile|null>(null),disciplines=ref<Discipline[]>([]),error=ref(''),ready=ref(false),toast=ref('');let timer:ReturnType<typeof setTimeout>;function notify(text:string){toast.value=text;clearTimeout(timer);timer=setTimeout(()=>toast.value='',4000)}async function init(){error.value='';try{profile.value=await api<Profile>('/profile');disciplines.value=(await api<{items:Discipline[]}>('/disciplines')).items;ready.value=true}catch(e){error.value=e instanceof Error?e.message:'连接失败'}}async function update(data:Partial<Profile>){profile.value=await api<Profile>('/profile',{method:'PATCH',body:JSON.stringify(data)})}return {profile,disciplines,error,ready,toast,init,update,notify}})
