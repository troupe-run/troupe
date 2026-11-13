## REMOVED Requirements

### Requirement: A pinned component's released workspace dependencies are pinned too
**Reason**: It refuses the state every release pull request leaves when it first releases a member that a pinned
component depends on: the manifest says released, but only the pinning pull request after the merge can pin it
(#411, found on #263). What it guarded, a `troupe-run` tag naming a needed member bare, the releases spec already
stops: while the bundle names any workspace member bare, its entry excludes its own commits, so it doesn't release
(#262).
**Migration**: None. The pinning pull request still pins each released member, and the check still fails a bundle
that names a member bare without excluding its commits (spec: releases).
