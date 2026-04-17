interface NavItem {
  id: string;
  label: string;
  hint: string;
  icon: React.ReactNode;
}

interface SidebarProps {
  activeItem?: string;
  onItemClick?: (id: string) => void;
}

export default function Sidebar({ activeItem = 'ask-ai', onItemClick }: SidebarProps) {
  const navItems: NavItem[] = [
    {
      id: 'ask-ai',
      label: 'Workspace',
      hint: 'Reasoning canvas',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 6h16M4 12h10M4 18h7" />
        </svg>
      ),
    },
    {
      id: 'my-files',
      label: 'Sources',
      hint: 'Workbooks · CSV · APIs',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
      ),
    },
    {
      id: 'conversations',
      label: 'History',
      hint: 'Sessions · usage',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 8v4l3 2m6-2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
  ];

  const handleClick = (id: string) => onItemClick?.(id);

  return (
    <aside className="w-64 h-screen bg-[#08090f] border-r border-white/8 flex flex-col">
      <div className="px-5 pt-6 pb-5 border-b border-white/8">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] flex items-center justify-center font-mono text-xs font-bold text-white tracking-[0.18em]">
            DI
          </div>
          <div className="min-w-0">
            <p className="text-[9px] uppercase tracking-[0.32em] text-gray-500 font-semibold">Hackathon 2026</p>
            <p className="text-sm font-semibold text-white leading-tight">Data Intelligence</p>
          </div>
        </div>
      </div>

      <div className="px-5 pt-5 pb-3">
        <button
          onClick={() => handleClick('ask-ai')}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_24px_rgba(130,67,234,0.28)] hover:shadow-[0_8px_28px_rgba(130,67,234,0.42)] transition"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M12 4v16m8-8H4" />
          </svg>
          New session
        </button>
      </div>

      <div className="px-5 pt-4 pb-2">
        <span className="text-[10px] uppercase tracking-[0.28em] text-gray-600 font-semibold">Navigate</span>
      </div>

      <nav className="flex-1 px-3 py-1">
        <ul className="space-y-1">
          {navItems.map((item) => {
            const isActive = activeItem === item.id;
            return (
              <li key={item.id}>
                <button
                  onClick={() => handleClick(item.id)}
                  className={`w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left transition ${
                    isActive
                      ? 'bg-white/[0.05] text-white'
                      : 'text-gray-400 hover:bg-white/[0.03] hover:text-gray-200'
                  }`}
                >
                  <span className={`flex h-8 w-8 items-center justify-center rounded-md border ${isActive ? 'border-[#8243EA]/40 bg-[#8243EA]/15 text-[#bca7ff]' : 'border-white/8 text-gray-500'}`}>
                    {item.icon}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs uppercase tracking-[0.16em] font-semibold">{item.label}</span>
                    <span className="block text-[11px] text-gray-500">{item.hint}</span>
                  </span>
                  {isActive && <span className="h-1.5 w-1.5 rounded-full bg-[#bca7ff]" />}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="px-5 py-4 border-t border-white/8">
        <div className="rounded-lg border border-white/8 bg-[#0d0e18] p-3">
          <p className="text-[10px] uppercase tracking-[0.22em] text-gray-500">Trust principles</p>
          <ul className="mt-2 space-y-1 text-[11px] text-gray-400 leading-snug">
            <li>· No black boxes</li>
            <li>· No string arithmetic</li>
            <li>· No orphan answers</li>
          </ul>
        </div>
      </div>
    </aside>
  );
}
