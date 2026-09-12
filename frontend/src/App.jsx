import { BrowserRouter, Link, NavLink, Route, Routes, Navigate, Outlet } from "react-router-dom";
import Home from "./pages/Home";
import Works from "./pages/Works";
import NotFound from "./pages/NotFound";
import "./App.css";
function DashboardLayout() {
  return <div className="app-shell">
    <header className="top-nav">
      <Link className="brand" to="/new-task">Video Maker</Link>
      <nav aria-label="主要導覽">
        <NavLink to="/new-task">製作影片</NavLink>
        <NavLink to="/works">我的作品</NavLink>
      </nav>
    </header>
    <Outlet />
  </div>;
}
function App() {
  return <BrowserRouter><Routes>
    <Route element={<DashboardLayout />}>
      <Route path="/" element={<Navigate to="/new-task" replace />} />
      <Route path="/new-task" element={<Home />} />
      <Route path="/works" element={<Works />} />
    </Route>
    {["/login", "/register", "/logout"].map(path =>
      <Route key={path} path={path} element={<Navigate to="/new-task" replace />} />
    )}
    <Route path="*" element={<NotFound />} />
  </Routes></BrowserRouter>;
}
export default App;
