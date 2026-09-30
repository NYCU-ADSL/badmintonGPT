import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonEn from "@/i18n/locales/en/common.json";
import commonZh from "@/i18n/locales/zh-TW/common.json";
import evaluationEn from "./locales/en.json";
import evaluationZh from "./locales/zh-TW.json";

export const LANGUAGE_KEY = "badmintongpt-evaluation-language";
function storedLanguage() {
  try { return localStorage.getItem(LANGUAGE_KEY) === "en" ? "en" : "zh-TW"; }
  catch { return "zh-TW"; }
}

// The common namespace belongs to the native answer renderer's UI controls.
// Evaluation copy has its own namespace; query and answer content stays unchanged.
void i18n.use(initReactI18next).init({
  lng: storedLanguage(), fallbackLng: "en", supportedLngs: ["en", "zh-TW"],
  defaultNS: "common", ns: ["common", "evaluation"],
  resources: {
    en: { evaluation: evaluationEn, common: { ...commonEn, message: { ...commonEn.message,
      videoPlaybackFailed: "This video could not be played. The source may be unavailable or its format unsupported by your browser.",
      retryVideo: "Retry playback", openOriginalVideo: "Open original video",
      videoAttachment: "Video attachment", fileAttachment: "File attachment", attachmentUnavailable: "Attachment unavailable",
    } } },
    "zh-TW": { evaluation: evaluationZh, common: { ...commonZh, message: { ...commonZh.message,
      videoPlaybackFailed: "無法播放此影片：來源可能已失效，或瀏覽器不支援此影片格式。",
      retryVideo: "重試播放", openOriginalVideo: "開啟原始影片",
      videoAttachment: "影片附件", fileAttachment: "檔案附件", attachmentUnavailable: "附件無法使用",
    } } },
  },
  interpolation: { escapeValue: false },
});
function updateDocumentLanguage() {
  document.documentElement.lang = i18n.resolvedLanguage === "en" ? "en" : "zh-Hant";
  document.title = `BadmintonGPT · ${i18n.t("evaluation", { ns: "evaluation" })}`;
}
i18n.on("languageChanged", updateDocumentLanguage);
updateDocumentLanguage();
export default i18n;
