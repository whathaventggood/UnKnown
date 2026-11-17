import {createApp} from 'vue'
import {createPinia} from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
router.afterEach(to=>{document.title=`${to.meta.title||'探索'} · UnKnown`})
createApp(App).use(createPinia()).use(router).mount('#app')
