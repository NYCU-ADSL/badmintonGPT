import React from "react";
import ReactDOM from "react-dom/client";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "@/i18n/locales/en/common.json";
import zh from "@/i18n/locales/zh-TW/common.json";
import { ThemeProvider } from "@/hooks/useTheme";
import "@/globals.css";
import "./style.css";
import App from "./App";

void i18n.use(initReactI18next).init({ lng: "zh-TW", fallbackLng: "en", defaultNS: "common",
  resources: { en: { common: en }, "zh-TW": { common: zh } }, interpolation: { escapeValue: false } });
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><ThemeProvider theme="light"><App /></ThemeProvider></React.StrictMode>,
);
