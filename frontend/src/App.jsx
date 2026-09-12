import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import Home from "./pages/Home";
import "./App.css";
function App() {
  return <BrowserRouter><Routes>
    <Route path="/" element={<Home />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></BrowserRouter>;
}
export default App;
