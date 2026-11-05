import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import App from './App.jsx'
import AdminRoute from './admin/AdminRoute.jsx'
import ThemeProvider from './theme/ThemeProvider.jsx'
import { readThemePreference } from './theme/themeRegistry.js'

document.documentElement.dataset.theme = readThemePreference().themeId

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/admin/*" element={<AdminRoute />} />
        <Route path="*" element={<App />} />
      </Routes>
    </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
)
