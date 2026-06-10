/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Invite link to the GOSHA Discord server (join-server funnel). */
  readonly VITE_DISCORD_INVITE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
