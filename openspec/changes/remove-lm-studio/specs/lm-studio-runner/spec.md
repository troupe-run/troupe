## REMOVED Requirements

### Requirement: The LM Studio runner is a self-contained plugin
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The runner talks to LM Studio only through the lmstudio package
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The library's dependencies are licensed and installable everywhere troupe runs
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The runner identifies itself as lm-studio
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The service comes from the run's runtime
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The runtime's endpoint is the library's host and port
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: An endpoint the library can't use is refused
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: A runtime with a credential is refused
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The runner's options are closed
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The runner checks LM Studio before it acknowledges the run
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The pre-run check finds a model that can call tools
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The runner publishes its platform requirements as data
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The model is loaded with the run's context length, and the length is reported
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The character is the system prompt and the direction the first message
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The model is offered the SDK's tools
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Each tool call is carried out by the SDK and checked against the effects
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: A call the library rejects is answered as troupe would answer it
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Every run has a turn limit and a token budget
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Assistant text is reported as turns
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: A round without a tool call ends the run
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The result carries the run's counts
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: A cost is estimated only from run start's price
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Every error result names its reason
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: A model other than the run's is reported
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: LM Studio's failures end the run as error results
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: A connection is retried only before any tool call has run
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Every limit the library applies is one of the runner's named settings
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Redirects are never followed
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The transcript is what the library exposes
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The library's own logging stays out of the run's output
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Summaries fit below the event limit
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Cancel and end of input stop the run at once
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The runner publishes its schemas
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: The runner conforms to the contract
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Fixtures pair real LM Studio exchanges with protocol events
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: A live test runs a real model only when asked
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: Every prediction stops at the context length
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).

### Requirement: A run told compact says the runner doesn't compact
**Reason**: The LM Studio runner is removed before 0.2.0 ships (#412, #413): its library, `lmstudio`, has stalled, which fails #319's "maintained client library".
**Migration**: None needed: the runner was never released. To run a model in LM Studio, define a runtime of your own for the anthropic runner (#415).
