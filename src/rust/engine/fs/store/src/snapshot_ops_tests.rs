use testutil::make_file;

use crate::{
  snapshot_tests::{expand_all_sorted, setup, STR, STR2},
  OneOffStoreFileByDigest, Snapshot, SnapshotOps, Store, SubsetParams,
};
use fs::{GlobExpansionConjunction, PosixFS, PreparedPathGlobs, StrictGlobMatching};
use hashing::Digest;

use std::fs::create_dir_all;
use std::path::Path;
use std::sync::Arc;

async fn get_duplicate_rolands(
  store: Store,
  base_path: &Path,
  posix_fs: Arc<PosixFS>,
  digester: OneOffStoreFileByDigest,
) -> (Digest, Snapshot, Snapshot) {
  create_dir_all(base_path.join("subdir")).unwrap();

  make_file(&base_path.join("subdir/roland1"), STR.as_bytes(), 0o600);
  let path_stats1 = expand_all_sorted(posix_fs).await;
  let snapshot1 = Snapshot::from_path_stats(store.clone(), digester.clone(), path_stats1)
    .await
    .unwrap();

  let (_store2, tempdir2, posix_fs2, digester2) = setup();
  create_dir_all(tempdir2.path().join("subdir")).unwrap();
  make_file(
    &tempdir2.path().join("subdir/roland2"),
    STR2.as_bytes(),
    0o600,
  );
  let path_stats2 = expand_all_sorted(posix_fs2).await;
  let snapshot2 = Snapshot::from_path_stats(store.clone(), digester2, path_stats2)
    .await
    .unwrap();

  let merged_digest = store
    .clone()
    .merge(vec![snapshot1.digest, snapshot2.digest])
    .await
    .unwrap();

  (merged_digest, snapshot1, snapshot2)
}

fn make_subset_params(globs: &[&str]) -> SubsetParams {
  let globs = PreparedPathGlobs::create(
    globs.iter().map(|s| s.to_string()).collect(),
    StrictGlobMatching::Ignore,
    GlobExpansionConjunction::AllMatch,
  )
  .unwrap();
  SubsetParams { globs }
}

#[tokio::test]
async fn subset() {
  let (store, tempdir, posix_fs, digester) = setup();

  let (merged_digest, snapshot1, snapshot2) =
    get_duplicate_rolands(store.clone(), tempdir.path(), posix_fs.clone(), digester).await;

  let subset_params1 = make_subset_params(&["subdir/roland1"]);
  let subset_roland1 = store
    .clone()
    .subset(merged_digest, subset_params1)
    .await
    .unwrap();
  assert_eq!(subset_roland1, snapshot1.digest);

  let subset_params2 = make_subset_params(&["subdir/roland2"]);
  let subset_roland2 = store
    .clone()
    .subset(merged_digest, subset_params2)
    .await
    .unwrap();
  assert_eq!(subset_roland2, snapshot2.digest);
}

#[tokio::test]
async fn subset_recursive_wildcard() {
  let (store, tempdir, posix_fs, digester) = setup();

  let (merged_digest, _, _) =
    get_duplicate_rolands(store.clone(), tempdir.path(), posix_fs.clone(), digester).await;

  let subset_params1 = make_subset_params(&["subdir/**"]);
  let subset_roland1 = store
    .clone()
    .subset(merged_digest, subset_params1)
    .await
    .unwrap();
  assert_eq!(merged_digest, subset_roland1);

  // **/* is a commonly-used alias for **.
  let subset_params2 = make_subset_params(&["subdir/**/*"]);
  let subset_roland2 = store
    .clone()
    .subset(merged_digest, subset_params2)
    .await
    .unwrap();
  assert_eq!(merged_digest, subset_roland2);
}
