/**
 * Google Picker - the native "choose a spreadsheet" dialog.
 *
 * This is what removes the old paste-a-spreadsheet-ID step. It also does real
 * work beyond convenience: Qonvo holds only the per-file `drive.file` scope, so
 * a file becomes reachable *because* the owner selected it here. There is no
 * type-the-id fallback - a hand-entered id would simply 404.
 *
 * The Picker script is loaded from Google on demand rather than bundled; it must
 * come from apis.google.com to work at all.
 */

const GAPI_SRC = "https://apis.google.com/js/api.js";

interface PickerConfigInput {
  accessToken: string;
  apiKey: string;
  appId: string;
}

// Minimal shape of the globals api.js installs; the real types aren't published.
interface GapiGlobal {
  load(name: string, callback: () => void): void;
}
interface PickerGlobal {
  PickerBuilder: new () => PickerBuilder;
  ViewId: { SPREADSHEETS: string };
  DocsView: new (viewId: string) => DocsView;
  Action: { PICKED: string; CANCEL: string };
  Feature: { NAV_HIDDEN: string };
}
interface DocsView {
  setIncludeFolders(v: boolean): DocsView;
  setSelectFolderEnabled(v: boolean): DocsView;
  setMode(mode: unknown): DocsView;
}
interface PickerBuilder {
  addView(view: DocsView | string): PickerBuilder;
  setOAuthToken(token: string): PickerBuilder;
  setDeveloperKey(key: string): PickerBuilder;
  setAppId(appId: string): PickerBuilder;
  enableFeature(feature: string): PickerBuilder;
  setTitle(title: string): PickerBuilder;
  setCallback(cb: (data: PickerResponse) => void): PickerBuilder;
  build(): { setVisible(v: boolean): void };
}
interface PickerResponse {
  action: string;
  docs?: { id: string; name?: string }[];
}

declare global {
  interface Window {
    gapi?: GapiGlobal;
    google?: { picker?: PickerGlobal };
  }
}

let scriptPromise: Promise<void> | null = null;

function loadGapiScript(): Promise<void> {
  if (window.gapi?.load) return Promise.resolve();
  // Cached so two rapid clicks don't inject the script twice.
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${GAPI_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("Failed to load Google Picker")));
      return;
    }
    const script = document.createElement("script");
    script.src = GAPI_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google Picker"));
    document.head.appendChild(script);
  }).catch((err) => {
    scriptPromise = null; // let a later attempt retry
    throw err;
  });

  return scriptPromise;
}

function loadPickerModule(): Promise<PickerGlobal> {
  return new Promise((resolve, reject) => {
    if (window.google?.picker) {
      resolve(window.google.picker);
      return;
    }
    const gapi = window.gapi;
    if (!gapi?.load) {
      reject(new Error("Google API script didn't initialise"));
      return;
    }
    gapi.load("picker", () => {
      const picker = window.google?.picker;
      if (picker) resolve(picker);
      else reject(new Error("Google Picker failed to initialise"));
    });
  });
}

/**
 * Open the spreadsheet chooser.
 *
 * Resolves with the chosen spreadsheet id, or `null` if the owner closed the
 * dialog - a cancel is a normal outcome, not an error, so callers shouldn't have
 * to distinguish it from a failure via exception handling.
 */
export async function openSheetPicker(config: PickerConfigInput): Promise<string | null> {
  await loadGapiScript();
  const picker = await loadPickerModule();

  return new Promise<string | null>((resolve) => {
    const view = new picker.DocsView(picker.ViewId.SPREADSHEETS)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false);

    new picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(config.accessToken)
      .setDeveloperKey(config.apiKey)
      .setAppId(config.appId)
      .enableFeature(picker.Feature.NAV_HIDDEN)
      .setTitle("Choose a spreadsheet for Qonvo")
      .setCallback((data) => {
        if (data.action === picker.Action.PICKED) {
          resolve(data.docs?.[0]?.id ?? null);
        } else if (data.action === picker.Action.CANCEL) {
          resolve(null);
        }
      })
      .build()
      .setVisible(true);
  });
}
