import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Satellite from './pages/Satellite'

const NAV_ITEMS = [
  { label: 'Satellite', to: '/', active: true },
  { label: 'Analysis', to: '/analysis', soon: true },
  { label: 'Vessels', to: '/vessels', soon: true },
]

function SystemStatus() {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface-900/60 border border-surface-700">
      <div className="relative flex w-2 h-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-60" />
        <span className="relative inline-flex rounded-full w-2 h-2 bg-amber-400" />
      </div>
      <span className="text-[10px] font-mono tracking-wider uppercase text-gray-500">
        Backend <span className="text-amber-300/90">Offline · UI Only</span>
      </span>
    </div>
  )
}

function Navbar() {
  return (
    <nav className="sticky top-0 z-40 bg-surface-800/90 backdrop-blur border-b border-surface-600">
      <div className="max-w-6xl mx-auto flex items-center justify-between gap-3 px-6 h-14">
        {/* Brand */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="relative flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-accent/30 to-sea/20 border border-accent/20">
            <svg className="w-5 h-5 text-sea" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-100 tracking-wide leading-tight">
              OIL SPILL <span className="text-sea">DETECTION</span>
            </p>
            <p className="text-[10px] font-mono text-gray-600 tracking-widest uppercase leading-tight">
              SAR Monitoring Suite
            </p>
          </div>
        </div>

        {/* Nav */}
        <div className="hidden md:flex items-center gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.label}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `px-3.5 py-1.5 text-[13px] font-medium rounded-md transition-colors duration-150 inline-flex items-center gap-2 ${
                  isActive && item.to === '/'
                    ? 'bg-accent/10 text-accent border border-accent/20'
                    : 'text-gray-500 hover:text-gray-200 hover:bg-surface-700/60 border border-transparent'
                }`
              }
            >
              {item.label}
              {item.soon && (
                <span className="text-[8px] font-mono px-1 py-px rounded bg-surface-700 text-gray-600 border border-surface-600">
                  SOON
                </span>
              )}
            </NavLink>
          ))}
        </div>

        {/* Status */}
        <div className="hidden sm:block">
          <SystemStatus />
        </div>
      </div>
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen app-bg">
        <Navbar />
        <main className="max-w-6xl mx-auto px-6 py-8">
          <Routes>
            <Route path="/" element={<Satellite />} />
          </Routes>
        </main>
        <footer className="border-t border-surface-700/60 mt-8">
          <div className="max-w-6xl mx-auto px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-2 text-[10px] font-mono text-gray-700">
            <span>OIL SPILL ANOMALY DETECTION · SMART INDIA HACKATHON</span>
            <span>FRONTEND PROTOTYPE v0.2.0 — NO BACKEND CONNECTION</span>
          </div>
        </footer>
      </div>
    </BrowserRouter>
  )
}