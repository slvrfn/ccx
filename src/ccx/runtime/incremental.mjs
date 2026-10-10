// Explicit incremental update; no periodic background jobs.
import {components} from "./common.mjs";
const {context, snapshots} = components();
const path = process.env.CCX_PROJECT_PATH;
try {
  const previous = snapshots.getCodebaseInfo(path);
  await context.getPreparedCollection(path); // Check live endpoint vs existing vector schema.
  const changes = await context.reindexByChange(path, undefined,
    previous?.requestIgnorePatterns || [], previous?.requestCustomExtensions || []);
  const rowCount = await context.getVectorDatabase().verify(
    context.getCollectionName(path)
  );
  if (rowCount <= 0) throw new Error("Incremental indexing produced zero stored chunks; "
    + "check source exclusions and run ccx reindex --full after correcting them.");
  if (changes.failed && changes.failed > 0) {
    throw new Error(`Partial incremental failure: ${changes.failed} operations failed`);
  }
  snapshots.setCodebaseIndexed(path, {
    indexedFiles: Math.max(0, (previous?.indexedFiles || 0) + changes.added - changes.removed),
    totalChunks: rowCount,
    status: previous?.indexStatus || "completed"
  });
  snapshots.saveCodebaseSnapshot();
  process.stdout.write(JSON.stringify({status: "indexed", ...changes}) + "\n");
} catch (error) {
  snapshots.setCodebaseIndexFailed(path, String(error));
  snapshots.saveCodebaseSnapshot();
  console.error(error);
  process.exitCode = 1;
}
// The Node Milvus client owns persistent sockets.
setTimeout(() => process.exit(process.exitCode || 0), 20);
