// Version-specific integration seam. Keep imports and schema assumptions here.
// No timer or automatic sync is created by this adapter.
import {Context, MilvusVectorDatabase} from "@zilliz/claude-context-core";
import {createEmbeddingInstance} from "@zilliz/claude-context-mcp/dist/embedding.js";
import {createMcpConfig} from "@zilliz/claude-context-mcp/dist/config.js";
import {SnapshotManager} from "@zilliz/claude-context-mcp/dist/snapshot.js";
import path from "node:path";

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
  async checkDimension(name, expected) {
    if (!await this.hasCollection(name)) return;
    const result = await this.client.describeCollection({collection_name: name});
    const field = result.schema?.fields?.find(item => item.name === "vector");
    const value = field?.type_params?.find(item => item.key === "dim")?.value;
    const stored = Number(value);
    if (!Number.isInteger(stored) || stored !== expected) {
      throw new Error(`Embedding dimension mismatch in ${name}: collection=${value ?? "unknown"}, `
        + `endpoint=${expected}. Back up any valid index, then run ccx reindex --full `
        + `for this project. Do not delete other projects' collections.`);
    }
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

export class CheckedContext extends Context {
  embeddingReady;
  async findIgnoreFiles(root) {
    // Docker build-context allowlists are not semantic source exclusions. The
    // upstream walker prunes "src" before !src/ can rescue it under a ** rule.
    // Keep .gitignore, .contextignore and other existing indexing exclusions.
    return (await super.findIgnoreFiles(root))
      .filter(filename => path.basename(filename) !== ".dockerignore");
  }
  async getPreparedCollection(root) {
    if (!this.embeddingReady) {
      this.embeddingReady = (async () => {
        const embedding = this.getEmbedding();
        const detected = await embedding.detectDimension();
        if (!Number.isInteger(detected) || detected < 1) {
          throw new Error("Embedding endpoint returned an invalid vector dimension.");
        }
        // The pinned OpenAI adapter's detectDimension returns but does not store it.
        embedding.dimension = detected;
        return detected;
      })();
    }
    const dimension = await this.embeddingReady;
    await this.getVectorDatabase().checkDimension(this.getCollectionName(root), dimension);
    return super.getPreparedCollection(root);
  }
  async indexCodebase(...args) {
    const stats = await super.indexCodebase(...args);
    if (stats.totalChunks <= 0) {
      throw new Error("Semantic indexing produced zero chunks. Check supported source extensions "
        + "and .gitignore/.contextignore exclusions. .dockerignore is not used by ccx semantic "
        + "indexing. No usable semantic index was created; fix exclusions and retry "
        + "with ccx reindex --full.");
    }
    return stats;
  }
}

export function components() {
  const config = createMcpConfig();
  const context = new CheckedContext({
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
