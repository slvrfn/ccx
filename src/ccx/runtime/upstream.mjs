// Adapt official handlers without the official entrypoint's unconditional 60s timer.
import {Server} from "@modelcontextprotocol/sdk/server/index.js";
import {StdioServerTransport} from "@modelcontextprotocol/sdk/server/stdio.js";
import {CallToolRequestSchema, ListToolsRequestSchema} from "@modelcontextprotocol/sdk/types.js";
import {ToolHandlers} from "@zilliz/claude-context-mcp/dist/handlers.js";
import {SyncManager} from "@zilliz/claude-context-mcp/dist/sync.js";
import {components} from "./common.mjs";

const {context, snapshots} = components();
const sync = new SyncManager(context, snapshots); // Deliberately no startBackgroundSync().
const handlers = new ToolHandlers(context, snapshots, sync);
const names = ["index_codebase", "search_code", "get_indexing_status", "clear_index",
               "ccx_verify_index"];
const server = new Server({name: "ccx-upstream", version: "0.1.0"}, {capabilities: {tools: {}}});
server.setRequestHandler(ListToolsRequestSchema, async () => ({tools: names.map(name => ({
  name, description: name, inputSchema: {type: "object", properties: {path: {type: "string"}},
                                        required: ["path"], additionalProperties: true}
}))}));
server.setRequestHandler(CallToolRequestSchema, async request => {
  const args = request.params.arguments;
  switch (request.params.name) {
    case "ccx_verify_index":
      try {
        const count = await context.getVectorDatabase().verify(
          context.getCollectionName(args.path), args.expected
        );
        return {content: [{type: "text", text: JSON.stringify({storedChunks: count})}]};
      } catch (error) {
        snapshots.setCodebaseIndexFailed(args.path, String(error));
        snapshots.saveCodebaseSnapshot();
        return {isError: true, content: [{type: "text", text: String(error)}]};
      }
    case "index_codebase": return handlers.handleIndexCodebase(args);
    case "search_code": return handlers.handleSearchCode(args);
    case "get_indexing_status": return handlers.handleGetIndexingStatus(args);
    case "clear_index": return handlers.handleClearIndex(args);
    default: throw new Error("Unknown tool");
  }
});
await server.connect(new StdioServerTransport());
