import { lazy, Suspense, useSyncExternalStore } from "react";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { auth, isAdmin, isStaff } from "./api";
import { SignIn } from "./pages/SignIn";
import { Chat } from "./pages/Chat";
import { Documents } from "./pages/Documents";
import { Privacy } from "./pages/Privacy";
import { Inbox } from "./pages/Inbox";

// charts and staff tools load only when opened
const Usage = lazy(() => import("./pages/Usage").then((m) => ({ default: m.Usage })));
const Dashboard = lazy(() => import("./admin/Dashboard").then((m) => ({ default: m.Dashboard })));
const Desk = lazy(() => import("./admin/Desk").then((m) => ({ default: m.Desk })));
const Users = lazy(() => import("./admin/Users").then((m) => ({ default: m.Users })));
const Campaigns = lazy(() => import("./admin/Campaigns").then((m) => ({ default: m.Campaigns })));

export function useUser() {
  return useSyncExternalStore(auth.subscribe, () => auth.user);
}

export function App() {
  const user = useUser();
  return (
    <BrowserRouter basename="/app">
      {!user ? (
        <SignIn />
      ) : (
        <div className="shell">
          <aside className="side">
            <div className="logo"><i />Sahaj</div>
            <NavLink to="/chat">💬 Chat</NavLink>
            <NavLink to="/documents">📄 Documents</NavLink>
            <NavLink to="/inbox">🔔 Offers</NavLink>
            <NavLink to="/privacy">🔒 Privacy & memory</NavLink>
            <NavLink to="/usage">📊 Usage</NavLink>
            {isStaff(user) && (
              <>
                <div className="nav-label">Team</div>
                <NavLink to="/desk">🎧 Desk</NavLink>
              </>
            )}
            {isAdmin(user) && (
              <>
                <NavLink to="/admin">📈 Dashboard</NavLink>
                <NavLink to="/admin/users">👥 Users</NavLink>
                <NavLink to="/admin/campaigns">📣 Campaigns</NavLink>
              </>
            )}
            <div className="grow" />
            <div className="who">
              <div><b>{user.name || user.username}</b></div>
              <div className="mute">{user.email}</div>
              <div className="row" style={{ marginTop: 8 }}>
                <span className="pill">{user.role}</span>
                <span className="pill">{user.tenant}</span>
                <button className="btn sm ghost" onClick={() => auth.signOut()}>Sign out</button>
              </div>
            </div>
          </aside>
          <main className="main">
            <Suspense fallback={<p className="mute">Loading…</p>}>
            <Routes>
              <Route path="/chat" element={<Chat />} />
              <Route path="/documents" element={<Documents />} />
              <Route path="/inbox" element={<Inbox />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/usage" element={<Usage />} />
              {isStaff(user) && <Route path="/desk" element={<Desk />} />}
              {isAdmin(user) && <Route path="/admin" element={<Dashboard />} />}
              {isAdmin(user) && <Route path="/admin/users" element={<Users />} />}
              {isAdmin(user) && <Route path="/admin/campaigns" element={<Campaigns />} />}
              <Route path="*" element={<Navigate to={isAdmin(user) ? "/admin" : "/chat"} replace />} />
            </Routes>
            </Suspense>
          </main>
        </div>
      )}
    </BrowserRouter>
  );
}
