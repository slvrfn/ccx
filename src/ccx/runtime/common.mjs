// Version-specific integration seam. Keep imports and schema assumptions here.
// No timer or automatic sync is created by this adapter.
import {Context, MilvusVectorDatabase} from "@zilliz/claude-context-core";
import {createEmbeddingInstance} from "@zilliz/claude-context-mcp/dist/embedding.js";
import {createMcpConfig} from "@zilliz/claude-context-mcp/dist/config.js";
import {SnapshotManager} from "@zilliz/claude-context-mcp/dist/snapshot.js";

console.log = console.error; // MCP stdout is protocol-only.

// Normalize legacy/new Milvus status codes and detect writes swallowed by Context.
class CheckedMilvus extends MilvusVectorDatabase {
  failures = [];
  wrapped = false;
  async ensureInitialized() {
    await super.ensureInitialized();
    if (this.wrapped) return;
    const owner = this;
    const writes = new Set(["insert", "deleteEntities", "createCollection", "createIndex",
                            "dropCollection", "upsert"]);
    this.client = new Proxy(this.client, {
      get(target, property) {
        const value = Reflect.get(target, property);
        if (typeof value !== "function") return value;
        return async (...args) => {
          try {
            const result = await value.apply(target, args);
            const status = result?.status;
            if (status && ((status.code && Number(status.code) !== 0) ||
                (status.error_code && status.error_code !== "Success"))) {
              throw new Error(`Milvus ${String(property)}: ${status.reason || JSON.stringify(status)}`);
            }
            return result;
          } catch (error) {
            if (writes.has(property)) owner.failures.push(String(error));
            throw error;
          }
        };
      }
    });
    this.wrapped = true;
  }
  async hasCollection(name) {
    // Some SDK releases ignore nonzero modern status.code in DescribeCollection.
    return (await this.listCollections()).includes(name);
  }
  async verify(name, expected) {
    if (this.failures.length) throw new Error(this.failures.join("; "));
    if (!await this.hasCollection(name)) throw new Error("Expected collection does not exist");
    await this.ensureLoaded(name);
    const result = await this.client.query({
      collection_name: name, output_fields: ["count(*)"], expr: "",
      consistency_level: "Strong",
    });
    const count = Number(result.data?.[0]?.["count(*)"]);
    if (!Number.isFinite(count) || count < 0 || (expected !== undefined && count !== expected)) {
      throw new Error(`Index verification failed: expected ${expected}, stored ${count}`);
    }
    return count;
  }
}

export function components() {
  const config = createMcpConfig();
  const context = new Context({
    embedding: createEmbeddingInstance(config),
    vectorDatabase: new CheckedMilvus({
      address: config.milvusAddress, token: config.milvusToken,
    }),
    hybridSearch: false,
  });
  context.addCustomIgnorePatterns([
    `${process.env.CCX_GRAPH_OUT}/**`, ".opencode/**", ".env", ".env.*", "*.pem", "*.key"
  ]);
  const snapshots = new SnapshotManager();
  snapshots.loadCodebaseSnapshot();
  return {context, snapshots};
}
