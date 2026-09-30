import { createApp } from 'vue'
import TDesign from 'tdesign-vue-next'
import App from './App.vue'
import router from './router'
import 'tdesign-vue-next/es/style/index.css'
import './styles/tokens.css'
import './styles/app.css'

createApp(App).use(TDesign).use(router).mount('#app')
