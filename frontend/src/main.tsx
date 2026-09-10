import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { App as AntdApp } from 'antd'
import { DialogProvider } from './components/DialogProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        {/* 为全局消息、弹窗提供 Ant Design 主题上下文。 */}
        <AntdApp>
          <DialogProvider>
            <App />
          </DialogProvider>
        </AntdApp>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
