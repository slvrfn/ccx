// Run from a directory whose node_modules contains the locked npm dependencies.
import assert from "node:assert/strict";
import {Context} from "@zilliz/claude-context-core";
import {ToolHandlers} from "@zilliz/claude-context-mcp/dist/handlers.js";
import {SnapshotManager} from "@zilliz/claude-context-mcp/dist/snapshot.js";
import {SyncManager} from "@zilliz/claude-context-mcp/dist/sync.js";
import {createMcpConfig} from "@zilliz/claude-context-mcp/dist/config.js";
import {MilvusVectorDatabase} from "@zilliz/claude-context-core";
assert.equal(typeof createMcpConfig, "function");
assert.equal(typeof MilvusVectorDatabase.prototype.getCollectionRowCount, "function");
for (const name of ["reindexByChange", "getCollectionName", "getVectorDatabase",
                   "findIgnoreFiles", "getPreparedCollection", "indexCodebase"]) {
  assert.equal(typeof Context.prototype[name], "function", `Context.${name}`);
}
for (const name of ["handleIndexCodebase", "handleSearchCode", "handleClearIndex",
                    "handleGetIndexingStatus"]) {
  assert.equal(typeof ToolHandlers.prototype[name], "function", `ToolHandlers.${name}`);
}
for (const name of ["setCodebaseIndexed", "setCodebaseIndexFailed", "loadCodebaseSnapshot"]) {
  assert.equal(typeof SnapshotManager.prototype[name], "function", `SnapshotManager.${name}`);
}
assert.equal(typeof SyncManager.prototype.startBackgroundSync, "function");
console.log("Pinned upstream adapter exports verified.");
