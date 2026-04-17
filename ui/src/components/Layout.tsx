import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Sidebar from './Sidebar';

interface LayoutProps {
  children: ReactNode;
  activeNavItem?: string;
  onNavItemClick?: (id: string) => void;
}

export default function Layout({ children, activeNavItem = 'chat', onNavItemClick }: LayoutProps) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  return (
    <div className="flex h-screen bg-[#07080f]">
      <Sidebar activeItem={activeNavItem} onItemClick={onNavItemClick} />

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="h-12 border-b border-white/8 flex items-center justify-end px-6 bg-[#08090f]">
          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-2">
              {user?.profile_picture ? (
                <img
                  src={user.profile_picture}
                  alt={user.full_name || user.email}
                  className="w-7 h-7 rounded-full"
                />
              ) : (
                <div className="w-7 h-7 bg-[linear-gradient(135deg,#8243EA,#2563EB)] rounded-full flex items-center justify-center">
                  <span className="text-white font-bold text-[11px]">
                    {user?.email?.charAt(0).toUpperCase()}
                  </span>
                </div>
              )}
              <p className="text-xs text-gray-400">{user?.full_name || user?.email}</p>
            </div>
            <button
              onClick={handleLogout}
              className="text-[10px] uppercase tracking-[0.18em] font-semibold text-gray-500 hover:text-white px-2 py-1 rounded transition"
            >
              Sign out
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-auto bg-[#07080f]">
          {children}
        </main>
      </div>
    </div>
  );
}
