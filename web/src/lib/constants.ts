// Community / support constants.
// The invite can be overridden at build time, but ships with the real one
// so every surface works even without build args.
export const DISCORD_INVITE =
  import.meta.env.VITE_DISCORD_INVITE || 'https://discord.gg/J3mbGjJFRq'
