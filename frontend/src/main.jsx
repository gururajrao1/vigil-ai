import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'

const savedTheme = localStorage.getItem('vigilai_theme')
document.documentElement.setAttribute(
  'data-theme',
  savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : 'dark',
)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
