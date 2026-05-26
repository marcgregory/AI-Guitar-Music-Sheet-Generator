export const ADMIN_TOKEN_STORAGE_KEY = "musicstudio_admin_token";
export const ADMIN_MODE_STORAGE_KEY = "musicstudio_admin_mode";

const enabledValues = new Set(["1", "true", "yes", "on", "enabled"]);

const isEnabled = (value: string | boolean | undefined | null): boolean => {
  if (typeof value === "boolean") return value;
  return value ? enabledValues.has(value.trim().toLowerCase()) : false;
};

export const isAdminModeEnabled = (): boolean => {
  const envFlag = import.meta.env.VITE_ADMIN_MODE;
  const storedFlag = window.localStorage.getItem(ADMIN_MODE_STORAGE_KEY);
  return isEnabled(envFlag) || isEnabled(storedFlag);
};

export const hasSavedAdminAccess = (): boolean => {
  const savedToken = window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY);
  return Boolean(savedToken?.trim()) || isAdminModeEnabled();
};
