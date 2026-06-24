import React, { useState, useEffect } from 'react';
import { ChevronDown, BarChart2, Search, Briefcase, Activity, Lock, Unlock, Zap } from 'lucide-react';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard_buy');
  const [activeDropdown, setActiveDropdown] = useState(null);
  const [userTier, setUserTier] = useState('free'); // Simulacija paketa: 'free' ali 'pro'

  // Stanja za Single Stock iskalnik
  const [ticker, setTicker] = useState('');
  const [singleData, setSingleData] = useState(null);
  const [singleLoading, setSingleLoading] = useState(false);
  const [singleError, setSingleError] = useState(null);

  // Stanja za Dashboard (Weekly Buy)
  const [dashboardData, setDashboardData] = useState([]);
  const [dashLoading, setDashLoading] = useState(false);

  const toggleDropdown = (menu) => {
    setActiveDropdown(activeDropdown === menu ? null : menu);
  };

  const handleNavClick = (tabId) => {
    setActiveTab(tabId);
    setActiveDropdown(null);
  };

  const getStatusColor = (status) => {
    if (status === "STRONG BUY") return "#15803d";
    if (status === "BUY") return "#0369a1";
    if (status === "SUPER-GROWTH TARGET") return "#a21caf";
    return "#ea580c";
  };

  // Funkcija za posamezno delnico (iz prej)
  const analyzeSingleStock = async () => {
    if (!ticker) return;
    setSingleLoading(true); setSingleError(null); setSingleData(null);
    try {
      const response = await fetch(`http://localhost:8000/api/stock/${ticker}`);
      const result = await response.json();
      if (result.status === "REJECTED" || result.status === "ERROR") {
        setSingleError(result.reason);
      } else {
        setSingleData(result);
      }
    } catch (err) {
      setSingleError("Napaka pri povezavi s strežnikom.");
    } finally {
      setSingleLoading(false);
    }
  };

  // Funkcija za Dashboard
  const loadDashboard = async () => {
    setDashLoading(true);
    try {
      // API-ju pošljemo naš trenutni paket, da ve, ali mora zakleniti STRONG BUY delnice
      const response = await fetch(`http://localhost:8000/api/dashboard/buy?tier=${userTier}`);
      const result = await response.json();
      setDashboardData(result.results || []);
    } catch (err) {
      console.error("Napaka pri nalaganju dashboarda", err);
    } finally {
      setDashLoading(false);
    }
  };

  // Naloži dashboard, ko prvič odpremo ali spremenimo paket
  useEffect(() => {
    if (activeTab === 'dashboard_buy') {
      loadDashboard();
    }
  }, [activeTab, userTier]);


  return (
    <div className="min-h-screen bg-[#0B0F19] text-slate-200 font-sans">
      
      {/* TOP NAVIGATION BAR */}
      <nav className="bg-[#111827] border-b border-slate-800 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-20">
            
            {/* LEVA STRAN: Logo in OGM Brand */}
            <div className="flex items-center cursor-pointer" onClick={() => handleNavClick('dashboard_buy')}>
              <img src="/ogm-logo.jpg" alt="OGM Logo" className="h-12 w-auto rounded border border-slate-700 shadow-lg" />
              <div className="ml-4">
                <h1 className="text-xl font-extrabold tracking-tight text-white bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">
                  OGM INVEST
                </h1>
                <p className="text-xs text-slate-400 tracking-wider">QUANTITATIVE PLATFORM</p>
              </div>
            </div>

            {/* SREDINA: Navigacijski zavihki */}
            <div className="hidden md:flex items-center space-x-2">
              <div className="relative">
                <button onClick={() => toggleDropdown('dashboard')} className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeDropdown === 'dashboard' || activeTab.includes('dashboard') ? 'bg-slate-800 text-blue-400' : 'text-slate-300 hover:bg-slate-800 hover:text-white'}`}>
                  <BarChart2 className="w-4 h-4 mr-2" /> Nadzorna plošča <ChevronDown className="w-4 h-4 ml-1" />
                </button>
                {activeDropdown === 'dashboard' && (
                  <div className="absolute left-0 mt-2 w-48 rounded-md shadow-2xl bg-[#1E293B] ring-1 ring-black ring-opacity-5 border border-slate-700 z-50">
                    <button onClick={() => handleNavClick('dashboard_buy')} className="w-full text-left px-4 py-3 text-sm text-slate-200 hover:bg-slate-700 hover:text-emerald-400 flex items-center">
                      <div className="w-2 h-2 rounded-full bg-emerald-500 mr-2"></div> BUY Analiza
                    </button>
                    <button onClick={() => handleNavClick('dashboard_sell')} className="w-full text-left px-4 py-3 text-sm text-slate-200 hover:bg-slate-700 hover:text-rose-400 flex items-center">
                      <div className="w-2 h-2 rounded-full bg-rose-500 mr-2"></div> SELL Analiza
                    </button>
                  </div>
                )}
              </div>

              <div className="relative">
                <button onClick={() => toggleDropdown('analysis')} className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeDropdown === 'analysis' || activeTab.includes('analysis') ? 'bg-slate-800 text-blue-400' : 'text-slate-300 hover:bg-slate-800 hover:text-white'}`}>
                  <Search className="w-4 h-4 mr-2" /> Analiza <ChevronDown className="w-4 h-4 ml-1" />
                </button>
                {activeDropdown === 'analysis' && (
                  <div className="absolute left-0 mt-2 w-48 rounded-md shadow-2xl bg-[#1E293B] ring-1 ring-black ring-opacity-5 border border-slate-700 z-50">
                    <button onClick={() => handleNavClick('analysis_single')} className="w-full text-left px-4 py-3 text-sm text-slate-200 hover:bg-slate-700 hover:text-blue-400">Posamezna delnica</button>
                  </div>
                )}
              </div>

              <button onClick={() => handleNavClick('portfolio')} className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'portfolio' ? 'bg-slate-800 text-emerald-400' : 'text-slate-300 hover:bg-slate-800 hover:text-white'}`}>
                <Briefcase className="w-4 h-4 mr-2" /> OGM Portfolio (Live)
              </button>
            </div>

            {/* DESNO: Profil uporabnika / Simulacija */}
            <div className="hidden md:flex items-center space-x-4">
               {/* Simulacija preklopa paketa za testiranje */}
               <div className="flex bg-slate-800 rounded-lg p-1 border border-slate-700">
                 <button onClick={() => setUserTier('free')} className={`px-3 py-1 text-xs font-bold rounded-md ${userTier === 'free' ? 'bg-slate-600 text-white' : 'text-slate-400'}`}>FREE</button>
                 <button onClick={() => setUserTier('pro')} className={`px-3 py-1 text-xs font-bold rounded-md flex items-center ${userTier === 'pro' ? 'bg-gradient-to-r from-amber-200 to-yellow-400 text-slate-900' : 'text-slate-400'}`}>
                   PRO+
                 </button>
               </div>
            </div>

          </div>
        </div>
      </nav>

      {/* MAIN CONTENT AREA */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        
        {/* =========================================================================
            MODUL 1: WEEKLY BUY ANALIZA (DASHBOARD)
        ========================================================================= */}
        {activeTab === 'dashboard_buy' && (
          <div className="animate-fade-in">
            <div className="flex justify-between items-end mb-8">
              <div>
                <h2 className="text-3xl font-bold text-white mb-2">Weekly BUY Analiza</h2>
                <p className="text-slate-400">Pregled najboljših nakupnih priložnosti po OGM V3 Moat pravilih.</p>
              </div>
              <button onClick={loadDashboard} disabled={dashLoading} className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg font-medium flex items-center text-sm transition-colors">
                <Activity className={`w-4 h-4 mr-2 ${dashLoading ? 'animate-spin' : ''}`} />
                {dashLoading ? 'Skeniram trg...' : 'Osveži podatke'}
              </button>
            </div>

            <div className="bg-[#1E293B] rounded-xl border border-slate-700 shadow-xl overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-800 border-b border-slate-700 text-slate-400 text-xs uppercase tracking-wider">
                    <th className="p-4 font-semibold">Ticker / Ime</th>
                    <th className="p-4 font-semibold">Sektor</th>
                    <th className="p-4 font-semibold">Razdalja MA</th>
                    <th className="p-4 font-semibold text-center">OGM Score</th>
                    <th className="p-4 font-semibold text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/50">
                  {dashboardData.map((row, idx) => (
                    <tr key={idx} className="hover:bg-slate-700/30 transition-colors relative">
                      
                      {/* Če je zaklenjeno, zameglimo Ticker in Ime */}
                      <td className="p-4">
                        {row.is_locked ? (
                          <div className="flex items-center space-x-3">
                            <div className="bg-slate-800 p-2 rounded-lg"><Lock className="w-5 h-5 text-amber-400" /></div>
                            <div>
                              <div className="font-bold text-slate-500 blur-[4px] select-none">XXXXX</div>
                              <div className="text-xs text-amber-400 font-medium">Zaklenjeno (PRO+)</div>
                            </div>
                          </div>
                        ) : (
                          <div>
                            <div className="font-bold text-blue-400 cursor-pointer hover:underline">{row.ticker}</div>
                            <div className="text-xs text-slate-400">{row.ime}</div>
                          </div>
                        )}
                      </td>
                      
                      <td className="p-4 text-sm text-slate-300">{row.sektor}</td>
                      
                      <td className="p-4 text-sm">
                        <span className={`font-bold ${row.components.ma_distance.raw >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {row.components.ma_distance.raw > 0 ? '+' : ''}{row.components.ma_distance.raw.toFixed(1)}%
                        </span>
                        <div className="text-[10px] text-slate-500 mt-1">{row.components.ma_distance.type}</div>
                      </td>
                      
                      {/* OGM Score pustimo viden vsem (FOMO efekt) */}
                      <td className="p-4 text-center">
                        <div className="inline-flex items-center justify-center bg-slate-800 border border-slate-600 px-3 py-1 rounded-md">
                          <span className="font-bold text-lg text-white">{row.ogm_score.toFixed(1)}</span>
                          <span className="text-xs text-slate-500 ml-1">/100</span>
                        </div>
                      </td>
                      
                      <td className="p-4 text-center">
                         <span className="text-xs font-bold px-3 py-1 rounded-full text-white" style={{ backgroundColor: getStatusColor(row.status) }}>
                            {row.status}
                         </span>
                      </td>

                      {/* Čez celotno vrstico "overlay" z gumbom za nadgradnjo, če je zaklenjeno */}
                      {row.is_locked && (
                         <div className="absolute inset-0 bg-[#0f172a]/40 backdrop-blur-[1px] flex justify-center items-center">
                            <button onClick={() => setUserTier('pro')} className="bg-gradient-to-r from-amber-400 to-yellow-500 text-slate-900 px-4 py-1.5 rounded-full text-xs font-bold flex items-center shadow-lg hover:scale-105 transition-transform">
                              <Zap className="w-3 h-3 mr-1" /> Odkleni s PRO+
                            </button>
                         </div>
                      )}

                    </tr>
                  ))}
                  {dashboardData.length === 0 && !dashLoading && (
                    <tr><td colSpan="5" className="p-8 text-center text-slate-500">Pritisni "Osveži podatke" za nalaganje delnic.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* =========================================================================
            MODUL 2: POSAMEZNA DELNICA (SEARCH)
        ========================================================================= */}
        {activeTab === 'analysis_single' && (
          <div className="animate-fade-in max-w-4xl mx-auto">
            <h2 className="text-3xl font-bold text-white mb-2">Diagnostika Posamezne Delnice</h2>
            <p className="text-slate-400 mb-8">Iskalnik in on-demand generiranje OGM profila v živo.</p>
            
            <div className="bg-[#1E293B] border border-slate-700 p-6 rounded-xl mb-8 flex gap-4">
              <input 
                type="text" 
                placeholder="Vpiši ticker (npr. TSLA)" 
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && analyzeSingleStock()}
                className="flex-1 bg-slate-800 border border-slate-600 text-white px-4 py-3 rounded-lg focus:outline-none focus:border-blue-500"
              />
              <button 
                onClick={analyzeSingleStock}
                disabled={singleLoading}
                className="bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-3 rounded-lg font-bold transition-colors disabled:opacity-50"
              >
                {singleLoading ? 'Računam...' : 'Analiziraj'}
              </button>
            </div>

            {singleError && (
              <div className="bg-rose-500/10 border border-rose-500/50 text-rose-400 p-4 rounded-lg mb-8">
                <strong className="block mb-1">Delnica zavrnjena ali napaka:</strong>
                {singleError}
              </div>
            )}

            {singleData && !singleLoading && (
              <div className="bg-[#1E293B] rounded-xl border border-slate-700 p-6 shadow-xl">
                <div className="flex justify-between items-start border-b border-slate-700 pb-6 mb-6">
                  <div>
                    <h2 className="text-2xl font-bold text-white mb-1">{singleData.ticker} - {singleData.ime}</h2>
                    <div className="text-slate-400">{singleData.sektor} • Trenutna cena: <strong className="text-white">${singleData.cena.toFixed(2)}</strong></div>
                  </div>
                  <div className="px-4 py-2 rounded-lg font-bold text-white" style={{ backgroundColor: getStatusColor(singleData.status) }}>
                    {singleData.status}
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                  <div className="bg-slate-800 p-4 rounded-lg border border-slate-700 text-center">
                    <div className="text-xs text-slate-400 uppercase font-bold mb-1">OGM Score</div>
                    <div className="text-2xl font-bold text-blue-400">{singleData.ogm_score.toFixed(1)}</div>
                  </div>
                  <div className="bg-slate-800 p-4 rounded-lg border border-slate-700 text-center">
                    <div className="text-xs text-slate-400 uppercase font-bold mb-1">Rast Prihodkov</div>
                    <div className="text-2xl font-bold text-white">{singleData.revenue_growth_pct}%</div>
                  </div>
                  <div className="bg-slate-800 p-4 rounded-lg border border-slate-700 text-center">
                    <div className="text-xs text-slate-400 uppercase font-bold mb-1">Razdalja od MA</div>
                    <div className={`text-2xl font-bold ${singleData.components.ma_distance.raw >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {singleData.components.ma_distance.raw > 0 ? '+' : ''}{singleData.components.ma_distance.raw.toFixed(1)}%
                    </div>
                  </div>
                  <div className="bg-slate-800 p-4 rounded-lg border border-slate-700 text-center">
                    <div className="text-xs text-slate-400 uppercase font-bold mb-1">Bruto Marža</div>
                    <div className="text-2xl font-bold text-white">{singleData.components.gross_margin.raw}%</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

      </main>
    </div>
  );
}

export default App;