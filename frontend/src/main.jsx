import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { TooltipProvider, ToastProvider, ToastViewport } from '@clairlabs-ai/prp-ui'
import '@clairlabs-ai/prp-ui/styles.css'
import './index.css'
import App from './App.jsx'

const savedTheme =
  localStorage.getItem('clair-mode') ||
  localStorage.getItem('vigilai_theme')
const mode = savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : 'dark'
document.documentElement.setAttribute('data-mode', mode)
document.documentElement.setAttribute('data-theme', mode)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <TooltipProvider>
      <ToastProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
        <ToastViewport />
      </ToastProvider>
    </TooltipProvider>
  </StrictMode>,
)
