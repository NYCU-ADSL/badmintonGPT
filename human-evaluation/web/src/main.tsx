import React from "react";
import ReactDOM from "react-dom/client";
import "./i18n";
import { ThemeProvider } from "@/hooks/useTheme";
import "@/globals.css";
import "./style.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><ThemeProvider theme="light"><App /></ThemeProvider></React.StrictMode>,
);
