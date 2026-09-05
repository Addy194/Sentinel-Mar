import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import { Layout } from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import CaseDetail from "@/pages/CaseDetail";
import Ingest from "@/pages/Ingest";
import Jobs from "@/pages/Jobs";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/cases/:id" element={<CaseDetail />} />
            <Route path="/ingest" element={<Ingest />} />
            <Route path="/jobs" element={<Jobs />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster theme="dark" position="bottom-right" toastOptions={{ style: { background: "#162032", border: "1px solid #334155", color: "#F8FAFC" } }} />
    </div>
  );
}

export default App;
