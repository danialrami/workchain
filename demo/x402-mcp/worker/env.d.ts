/* Secret bindings are not emitted by `wrangler types`; keep this supplemental declaration in sync. */
interface Env {
  MCP_ADDRESS: string;
  WORKCHAIN_ORIGIN_URL: string;
  WORKCHAIN_BACKEND_TOKEN: string;
}
