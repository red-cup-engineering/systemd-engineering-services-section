# Systemd unit inventory observation

Reads user-manager unit inventories, timer inventories, resource-accounting observations and checkout-bound unit references. Resource receipt functions compare before and after observations using the package's existing accounting rules.

## Commands

Requires Node.js 22 or later and access to the selected user manager. Install the declared dependencies with `npm install` using the registry configuration for the package scope.

```sh
observe-unit-inventory --host local
observe-set-of-unit-resource-accounting --host local --unit example.service
derive-set-of-unit-resource-receipts --before before.json --after after.json
observe-set-of-checkout-bound-units --host local --root /path/to/checkout
```

A host is `local` or a bare SSH destination. Remote observation uses the caller's SSH environment. Inventory and accounting commands print JSON. Without `--unit`, accounting collects the service-unit names found in the live inventory and installed unit files. The receipt command accepts either one observation or an array in each input file.

Checkout observation accepts repeated `--allow` options for unit names. Its JSON result and exit code distinguish the observed checkout state and refusals. Missing required arguments return a usage failure.

## JavaScript interface

The root export provides `observeUnitInventory(host, { run })` and `serviceUnitNames(host, { run })`. Supply the process runner explicitly. The `./run-systemctl` export provides the real runner, and tests can inject a recording implementation.

The `./resource-accounting`, `./resource-receipts` and `./checkout-bound-units` subpaths expose the corresponding observation and derivation functions. `./observe-unit-inventory-verb` adapts inventory to the containing computer-system engine's verb interface.

## Verification

```sh
npm test
npm run check
```

The existing native suite checks local and SSH argument construction, host admission, resource counters, before/after receipts and checkout-bound unit observation using injected runners and fixtures. Package qualification replays that suite against the installed artifact, imports every declared entry point and checks all four command targets.
