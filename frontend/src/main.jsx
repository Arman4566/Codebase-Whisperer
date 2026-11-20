import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

const root = document.getElementById("root");
root.dataset.ready = "1";
createRoot(root).render(<App />);
