:robot: I have created a release *beep* *boop*
---


<details><summary>troupe: 0.2.0</summary>

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-v0.1.0...troupe-v0.2.0) (2026-11-20)


### ⚠ BREAKING CHANGES

* **openai:** the OpenAI runner is troupe-run's openai extra, no longer in the base install; install troupe-run[openai] or [all].
* **runner-ollama:** troupe-run no longer installs the Ollama runner by default; install troupe-run[ollama] (or troupe-run[all]).
* **runs:** Run.Started requires on_context_full, so a run started before this no longer reads. There are no theatres to migrate.
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **protocol:** a run that hasn't ended has nothing from its end
* **runner-protocol:** say when a retry wasn't safe
* **protocol:** records and messages that leave out these fields, or hold runner_reported or a start's clones, no longer validate.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* audit every run's changes against its declared effects ([3f5e31e](https://github.com/troupe-run/troupe/commit/3f5e31e85ef2d2b4f421a75d4fd918cd7ee7ffb4))
* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **claude-code:** capture fixtures through the runner's own rules ([2e25dce](https://github.com/troupe-run/troupe/commit/2e25dce0494625c266e59da14c113fb9c888f60d))
* **claude-code:** translate declared effects into permission rules ([7ed5cf1](https://github.com/troupe-run/troupe/commit/7ed5cf1e6ec9596af2fafde03e392a6084546b46))
* **cli:** config commands read and show bracketed paths ([4d0d039](https://github.com/troupe-run/troupe/commit/4d0d0397be7188acd8bf82bea0fc9a8c8c12d15a))
* **cli:** init names the extra an audition's runner comes with ([7083013](https://github.com/troupe-run/troupe/commit/7083013781cf477f1468320815391c46ca3b32cd)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **cli:** init's allow step says to add it to the shell profile once ([7956d0b](https://github.com/troupe-run/troupe/commit/7956d0b5ab017892558e275179f26308a1d111a8))
* **cli:** show a run's audit in status and logs ([3b1f305](https://github.com/troupe-run/troupe/commit/3b1f3056b4f41ba4b85dc7a3818aa80427934518))
* **cli:** troupe init, and init --audition for an example actor ([fc34264](https://github.com/troupe-run/troupe/commit/fc342642ac4ec34ef08369688b925cbda3c00fcf))
* **config:** read and show config paths with brackets for any key ([d2e2bd6](https://github.com/troupe-run/troupe/commit/d2e2bd65fee97daeed93afa8eb380766fcbeffcf))
* **config:** refuse an actor whose runner can't use its runtime ([ed15536](https://github.com/troupe-run/troupe/commit/ed1553634db7689202f6bd9bda6467aba1c89a5f))
* **config:** refuse changes only to an actor whose runner is missing ([1308a17](https://github.com/troupe-run/troupe/commit/1308a1752d907cbc1a22d5f329002da05878f23c)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **init:** warm a runner's engine before its first run ([23662dc](https://github.com/troupe-run/troupe/commit/23662dc55a76e351ede838b9bdd1772b0d955062))
* **lm-studio:** stop at the context limit, and warn it won't compact ([a45df7b](https://github.com/troupe-run/troupe/commit/a45df7b2516f79aa9c7c11bcc439ebb10c1d6df6))
* **ollama:** a run told to compact stubs old tool results to fit ([30a4a52](https://github.com/troupe-run/troupe/commit/30a4a52cbcff9203574fbeb1531d9317c49887c4))
* **openai:** a run told to compact stubs old outputs after a refusal ([43a2891](https://github.com/troupe-run/troupe/commit/43a28914cff30c7952889317356d09d851cb0047))
* **openai:** send the OpenAI runner's requests through openai ([3a732a3](https://github.com/troupe-run/troupe/commit/3a732a38830a9f934ca0941d9038e62fa689667c)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **protocol:** a run that hasn't ended has nothing from its end ([81db7f0](https://github.com/troupe-run/troupe/commit/81db7f054e201428a9fbd649a129022fa7b0eba9)), closes [#313](https://github.com/troupe-run/troupe/issues/313)
* **protocol:** estimate a run's cost from a price troupe resolves ([b809b61](https://github.com/troupe-run/troupe/commit/b809b61b451cd5aeac6154eaa0cd16ab8f5b4ba9))
* **protocol:** refuse a runner that isn't installed, naming its extra ([a81a3fb](https://github.com/troupe-run/troupe/commit/a81a3fb2b9c13478c763cc93ea9995648d9a40d4)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **protocol:** require the fields troupe always writes ([1222e08](https://github.com/troupe-run/troupe/commit/1222e08981ebc1c06d978a5f200c5ff670b71726)), closes [#305](https://github.com/troupe-run/troupe/issues/305)
* **runner-anthropic:** add a runner for the Anthropic Messages API ([0d3bd99](https://github.com/troupe-run/troupe/commit/0d3bd995def2ce4d24be238614864170fb109465))
* **runner-lm-studio:** run actors on LM Studio through lmstudio ([117f688](https://github.com/troupe-run/troupe/commit/117f688024e3d7e39f6c8c1e8e896ac4b0337319)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runner-mistralrs:** add the in-process runner's package and engine ([50518ab](https://github.com/troupe-run/troupe/commit/50518abcf64487da09a7a1f0131272e6e454915b))
* **runner-mistralrs:** run the conversation, with tests and docs ([096e135](https://github.com/troupe-run/troupe/commit/096e135cc0c099600146355d63cebab06d6c9daf))
* **runner-ollama:** install the Ollama runner as troupe-run[ollama] ([0760a38](https://github.com/troupe-run/troupe/commit/0760a383bdb64680106cfa4fcb83d476cadbf875))
* **runner-ollama:** take the endpoint and model from the runtime ([ff86f85](https://github.com/troupe-run/troupe/commit/ff86f85add2bbc545f1a47bb25f36595339c99d2)), closes [#289](https://github.com/troupe-run/troupe/issues/289)
* **runner-ollama:** talk to Ollama and check what it requires ([#277](https://github.com/troupe-run/troupe/issues/277)) ([8893bae](https://github.com/troupe-run/troupe/commit/8893baef1b7a6055235fd1a0da79ea59f216d140))
* **runner-openai:** estimate a run's cost from troupe's price ([5307f14](https://github.com/troupe-run/troupe/commit/5307f147e9aeb7e994ad8b7a655408c376edf9f1))
* **runner-openai:** rename to openai, ship it, and give it an audition ([f4cedac](https://github.com/troupe-run/troupe/commit/f4cedac9f3ce3e90af0b397c62a4910be6f3b997))
* **runner-protocol:** a context event for content lost mid-run ([66a0127](https://github.com/troupe-run/troupe/commit/66a012776a1b8aa37ff544397b9d5096b6ef63ce))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** say when a retry wasn't safe ([0dda581](https://github.com/troupe-run/troupe/commit/0dda58103d34b1aece6cf01c9c8636776dd36168)), closes [#378](https://github.com/troupe-run/troupe/issues/378)
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** pass coverage.py's subprocess setting to runners, and nothing else ([ed17ccd](https://github.com/troupe-run/troupe/commit/ed17ccd5fd4138acdb0cfedc69b8f55d1d4970e1))
* **runners:** remove the LM Studio runner before 0.2.0 ([26e9b7a](https://github.com/troupe-run/troupe/commit/26e9b7ac949237f3844a45513473525b63169b75))
* **runs:** actors opt in to compaction; policy can allow or forbid it ([27c8f6f](https://github.com/troupe-run/troupe/commit/27c8f6f53ddef172961180fd8f7db8bf2096253a))
* **runs:** audit every started run and record what it found ([ac99c89](https://github.com/troupe-run/troupe/commit/ac99c8938a494fff2f14bfa89dfd708e67427107))
* **runs:** keep the notices a run raises in its history ([2ceae43](https://github.com/troupe-run/troupe/commit/2ceae432c1934a15318e88b6d60832b8a00bca23))
* **runs:** perform runs the Ollama runner by name ([#277](https://github.com/troupe-run/troupe/issues/277)) ([d50be0c](https://github.com/troupe-run/troupe/commit/d50be0c411cf9b1d87510e17ca8f403de6769e79))
* **runs:** record and show a context event like any run event ([76ccf97](https://github.com/troupe-run/troupe/commit/76ccf97d642d765133c3db593eb18392049f506e))
* **runs:** refuse a runtime the environment makes unfit for its runner ([f722217](https://github.com/troupe-run/troupe/commit/f7222172dd2c68925dd8d9d6d8da55e2637fb253))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **runtimes:** add the anthropic built-in runtime for Claude's API ([c66fb97](https://github.com/troupe-run/troupe/commit/c66fb97feb5a03e783a7e388a3ada391ca4acbe1))
* **runtimes:** fit a built-in runtime only to the runner it's for ([6e1df8e](https://github.com/troupe-run/troupe/commit/6e1df8e385a45ccd027aafeccfe235b5d96327b5)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runtimes:** judge the lm-studio runner's fit, https included ([4f07f83](https://github.com/troupe-run/troupe/commit/4f07f836c03c1ee890288d3f7d49b8e0d1b5ad70)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runtimes:** name runtimes in config and hand runs their credential ([5e14751](https://github.com/troupe-run/troupe/commit/5e14751ac70c364326dedd44a2e6b8c8186cb05c))
* **runtimes:** point the built-in lm-studio runtime at LM Studio's root ([15b128e](https://github.com/troupe-run/troupe/commit/15b128eec53671d9f2ac69d4fabd3fa82faaf267)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runtimes:** refuse a credential holding whitespace in core ([cac94eb](https://github.com/troupe-run/troupe/commit/cac94ebbed4a886a4aaf4119b16c5e9f9a015df9))
* **scripted:** a tool step that runs calls through the SDK's tools ([949996a](https://github.com/troupe-run/troupe/commit/949996a22aeaa537ab821abebb752af75c74c5d5))
* **vcs:** say whether a directory is in a repository ([09abe93](https://github.com/troupe-run/troupe/commit/09abe93e078ef6635ab10a4e240ca79ddc6a852e))


### Bug Fixes

* act on the review of [#338](https://github.com/troupe-run/troupe/issues/338) ([76457e4](https://github.com/troupe-run/troupe/commit/76457e4de9fa3327d1cf5093e0aa532e85eac35a)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **cli:** init says to change the character with config set ([345b712](https://github.com/troupe-run/troupe/commit/345b71241d84aadcabf283c1351d3cdc68298c38))
* **cli:** let config refuse an option on a missing runner with its path ([f40d8b0](https://github.com/troupe-run/troupe/commit/f40d8b086ab84d9c8f86da821670f7257869eeb8)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **cli:** name a config set argument with no = by position ([e7addbb](https://github.com/troupe-run/troupe/commit/e7addbb01f0f78b90ab059ac45b8569c38f122e2))
* **cli:** never repeat a value config set can't type ([cf16bd2](https://github.com/troupe-run/troupe/commit/cf16bd270562c5129525a5812d37a288f05ff1c0))
* **config:** cut a malformed path at a bracket it failed in ([fd47af2](https://github.com/troupe-run/troupe/commit/fd47af2e8df512dbf180f765bb8980a43f183db9))
* **config:** judge fit only for runtimes with no problems of their own ([f7ea12c](https://github.com/troupe-run/troupe/commit/f7ea12c4fa0d60e327d071808e5aa350c186eba1))
* **config:** keep an old Ollama actor's endpoint in the move's fix ([903f817](https://github.com/troupe-run/troupe/commit/903f8170ab4929eeb82c9bc498b13abfb21aeb0c))
* **config:** name an uncovered expect path by position ([f6778e5](https://github.com/troupe-run/troupe/commit/f6778e59e55019651847c89bdeed1e15d6b6dc1c))
* **config:** name the closest alternative's failures, not its oneOf ([f3ef084](https://github.com/troupe-run/troupe/commit/f3ef084f2a089319b4e96f4c6b56f4d480d5481f))
* **config:** never name a key set inside a value ([c5dfa80](https://github.com/troupe-run/troupe/commit/c5dfa807f5da9ab4a33292594c87ac831982f8f2))
* **config:** never name a map key set inside a value ([b86c680](https://github.com/troupe-run/troupe/commit/b86c68030eac781003920170e53193e9f76ddc05))
* **config:** never name the keys leading to a null in a value ([e6710ab](https://github.com/troupe-run/troupe/commit/e6710aba13d319f14e4922f2d629db9435753ba5))
* **config:** never repeat a value core refuses for its shape ([b5a95bd](https://github.com/troupe-run/troupe/commit/b5a95bd9155a76acc3953d42501d0800163f5288))
* **config:** offer only runtimes config would accept, check CredentialName ([7627965](https://github.com/troupe-run/troupe/commit/7627965de2c7f68e5ab0a8750dfb163e54083412))
* **config:** price a model whose name holds a dot in brackets ([3a77deb](https://github.com/troupe-run/troupe/commit/3a77deb1891beb00eb7749077de96b5046efbc6c))
* **config:** refuse actors set to a value rather than crash ([8eeddc7](https://github.com/troupe-run/troupe/commit/8eeddc7b4e126b40332d99b3a291e47d94275824)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **config:** show _move_fix's paths through shown after the rebase ([9d80c0f](https://github.com/troupe-run/troupe/commit/9d80c0f8a0330fb5f2d59643347dba23162aedc8))
* **config:** show a credential name from the environment by its setter ([7924383](https://github.com/troupe-run/troupe/commit/7924383dd0c43ada4dbdf7a9ac73a0e6797e976a))
* **config:** show a missing runner's path as main now shows paths ([fcaf8e2](https://github.com/troupe-run/troupe/commit/fcaf8e25a8ffb13b78203f7d7dc9df709348f312)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **config:** show hand-built config paths in messages through shown ([d41a538](https://github.com/troupe-run/troupe/commit/d41a53843dc22b46e6e9eca0e6f3bb6a6e53c636))
* **config:** write every actor schema field to the actor's file ([527dee6](https://github.com/troupe-run/troupe/commit/527dee62030a6a85dac1d8bc9a7e3afb5ce53c6a))
* **docs:** keep one audition row, and refuse duplicate glossary terms ([3423843](https://github.com/troupe-run/troupe/commit/34238436c1b20f36a10ab203403ec5aba728c015)), closes [#264](https://github.com/troupe-run/troupe/issues/264)
* **docs:** link a changelog only once it exists ([7a941c2](https://github.com/troupe-run/troupe/commit/7a941c2d5a6069777338f01db88523425ff51e3b)), closes [#366](https://github.com/troupe-run/troupe/issues/366)
* **host:** make keys that mask to one a violation around a record ([0622add](https://github.com/troupe-run/troupe/commit/0622add4a08c03b2cac3a5a95437a43e26ccd1fb))
* **host:** parse a runner's line before masking it ([14245f6](https://github.com/troupe-run/troupe/commit/14245f620ae341248e1df7a7f961d6a2dbe992d0))
* **host:** refuse messages masking can't keep whole; act on review ([516de54](https://github.com/troupe-run/troupe/commit/516de548f61ed10210c5eb0e35bfd0bb9c8ee84f))
* **init:** read only the policy flag init needs ([cce6274](https://github.com/troupe-run/troupe/commit/cce6274656dd43b3f336117bafe0a47e65fd488f))
* **masking:** end record masking when a pass changes nothing ([932ee7c](https://github.com/troupe-run/troupe/commit/932ee7cf2e7a8b77e1c77bad7a2d682216fd4deb))
* **masking:** keep a transcript record that is JSON valid JSON ([c8d2d0b](https://github.com/troupe-run/troupe/commit/c8d2d0b1574250096d9288715388df10ae857626)), closes [#438](https://github.com/troupe-run/troupe/issues/438)
* **platform:** give no namespace token for a part that can't be decoded ([cebc21c](https://github.com/troupe-run/troupe/commit/cebc21c2113d7b913e257e5889dcf722ca447483))
* **platform:** wait for a command that has closed its output to exit ([d1493bc](https://github.com/troupe-run/troupe/commit/d1493bc310c0785107f2cf0e8ba8e6a2169a977f))
* **protocol:** say a malformed path's offset can pass its text ([77a0825](https://github.com/troupe-run/troupe/commit/77a08258a830b5daff9abc6fddd0153174ed187e))
* **protocol:** say what the actor schema's $schema holds ([2894f36](https://github.com/troupe-run/troupe/commit/2894f3617b2c061ce2f8be684f14d97404e88f6c))
* **runner-lm-studio:** end a failed reconnect as network, bound the check ([16917cc](https://github.com/troupe-run/troupe/commit/16917cccf3a029ead6037777396bbaab069adc9e)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runner-mistralrs:** act on the review of [#422](https://github.com/troupe-run/troupe/issues/422) ([417a843](https://github.com/troupe-run/troupe/commit/417a843a5849cdc06d41d7533b28a75c828ee113))
* **runner-mistralrs:** check the answer comes before the load ([2f7e3e5](https://github.com/troupe-run/troupe/commit/2f7e3e5e4a71f6170938190a2ab729c106eebec2))
* **runner-openai:** act on an independent review of unread files ([a00c1aa](https://github.com/troupe-run/troupe/commit/a00c1aa509c357ac3a662e92b3cd61a4f181ef22))
* **runner-openai:** act on the split review of the whole PR ([b3f1910](https://github.com/troupe-run/troupe/commit/b3f191015083b66515900bed2018bbdaa15e3428))
* **runner-protocol:** act on the review of the record kinds ([38b8503](https://github.com/troupe-run/troupe/commit/38b8503d3ce1cfbe403c31f7d80d4e9721deec02)), closes [#294](https://github.com/troupe-run/troupe/issues/294)
* **runner-protocol:** act on the slice reviews of record kinds ([87d51d8](https://github.com/troupe-run/troupe/commit/87d51d83149f7547852f81721a84a2e9d627daef)), closes [#294](https://github.com/troupe-run/troupe/issues/294)
* **runner-protocol:** say a retry can name five reasons ([723516f](https://github.com/troupe-run/troupe/commit/723516f2c7fec4bbc7cc881325471e642cb160e5))
* **runner-protocol:** say usage.inputTokens leaves out cache tokens ([f6d80b5](https://github.com/troupe-run/troupe/commit/f6d80b50f51845773243bcf22ebbfadbbc985da5))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runs:** drop an unpriced cost estimate with a notice, not a crash ([a6fa0d2](https://github.com/troupe-run/troupe/commit/a6fa0d23630513d904aca5b93d55dae97f3edd39))
* **runs:** keep recording when a run event's waiter is cancelled ([82511b4](https://github.com/troupe-run/troupe/commit/82511b4c300c5ab16b850e8ca7203369d72eb89a))
* **runs:** list run.estimate-dropped with the run host's notices ([977cd80](https://github.com/troupe-run/troupe/commit/977cd808432f71acfbd5a9226d261987179d64f3))
* **runs:** read a held lease whose perform has ended as interrupted ([c6c3300](https://github.com/troupe-run/troupe/commit/c6c3300af6b9884b95df99a5e9fe5444f4775118))
* **runs:** store a dropped estimate's oversized result as a message ([0c11825](https://github.com/troupe-run/troupe/commit/0c11825a6208e270882e61821ab2557f0b2a2207))
* **runs:** trust a lease's ended pid only from the reader's namespace ([8737ddb](https://github.com/troupe-run/troupe/commit/8737ddb0edee8186b5a2bfe5663edec701eba8d2))
* **runtimes:** carry the anthropic runner onto endpointless runtimes ([f5c5316](https://github.com/troupe-run/troupe/commit/f5c53163b412294233593527418fdca5a90734c4))
* **runtimes:** count // as a path, as the Ollama runner does ([9be390c](https://github.com/troupe-run/troupe/commit/9be390c3d293df4d64b9a282df9746347a6e6f38))
* **runtimes:** never echo a refused runtime variable's value ([610096d](https://github.com/troupe-run/troupe/commit/610096d9e03d08379a6db6c81e1928f1343beba7))
* **runtimes:** never repeat a credential's variable name from the env ([0cabf18](https://github.com/troupe-run/troupe/commit/0cabf18e98fd6ed23863a983658652a79fbd6bfb))
* **runtimes:** say an env-named credential variable must hold a name ([2fcbafd](https://github.com/troupe-run/troupe/commit/2fcbafda1a871d3176a5abe6f20597bf10eac387))
* **runtimes:** the actor's model beats TROUPE_RUNTIME_&lt;NAME&gt;_MODEL ([782d068](https://github.com/troupe-run/troupe/commit/782d068afe831a98ea6348e54d9a1b06023a76ec))
* **sdk:** never repeat an endpoint refused in run/start ([8619164](https://github.com/troupe-run/troupe/commit/8619164f89eaccaa594c0e9ada5b3eded280ebda))
* **sdk:** refuse a credential a request header can't carry ([b691e3f](https://github.com/troupe-run/troupe/commit/b691e3fe59177461d02de09fed6fff85329b81d9))
* **store:** never reuse a notification id across an order rebuild ([24e817d](https://github.com/troupe-run/troupe/commit/24e817d5e19cf53fa08793b6c2b1f87dade2f3e8)), closes [#454](https://github.com/troupe-run/troupe/issues/454)
* **store:** read the order log as it is now before numbering events ([5292580](https://github.com/troupe-run/troupe/commit/52925800bf2db990755136a714c78d80c37da9d6))
* **test:** leave git lock files out of a copied theatre ([7deebc0](https://github.com/troupe-run/troupe/commit/7deebc058a909247af937697b66a3ece57501108))
* **test:** make the theatre template directory only when one is built ([8f45cd4](https://github.com/troupe-run/troupe/commit/8f45cd4278f05cd9eb3dc3587590431c0a5ad117))
* **vcs:** name an unborn branch as git will once it's born ([f60d21d](https://github.com/troupe-run/troupe/commit/f60d21db6c4946bf32729219abc576f65dbc3e4b)), closes [#388](https://github.com/troupe-run/troupe/issues/388)


### Performance Improvements

* **cli:** load only what each command needs ([#383](https://github.com/troupe-run/troupe/issues/383)) ([44fb4ca](https://github.com/troupe-run/troupe/commit/44fb4ca99d6756864ae815445350df1544b1f2e4))
* **core:** read runs and config without YAML or schemas ([#383](https://github.com/troupe-run/troupe/issues/383)) ([dc2cf56](https://github.com/troupe-run/troupe/commit/dc2cf56a1a965a9a4d43863c1c6b44e18d460231))
* **masking:** mask large strings a window at a time ([fa11ff4](https://github.com/troupe-run/troupe/commit/fa11ff463b8293919a7f667c9d79554fd0a19067))
* **masking:** replace every span across values in one pass ([cd12fdd](https://github.com/troupe-run/troupe/commit/cd12fdd7b00e21e814da1744535fd5d89b5391e5))
* **platform:** return from run_to_completion when the command ends ([2a7e15a](https://github.com/troupe-run/troupe/commit/2a7e15a4ed2fc737c0211847fda1993480791850))
</details>

<details><summary>troupe-plugin-sdk: 0.1.0</summary>

## 0.1.0 (2026-11-20)


### ⚠ BREAKING CHANGES

* **sdk:** EventNumbering requires send_context.
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** say when a retry wasn't safe
* **protocol:** records and messages that leave out these fields, or hold runner_reported or a start's clones, no longer validate.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **plugin-sdk:** define what a credential's value may hold, once ([d97ce8f](https://github.com/troupe-run/troupe/commit/d97ce8f109d062215c690f93a8cffbf3e1b82516))
* **protocol:** estimate a run's cost from a price troupe resolves ([b809b61](https://github.com/troupe-run/troupe/commit/b809b61b451cd5aeac6154eaa0cd16ab8f5b4ba9))
* **protocol:** require the fields troupe always writes ([1222e08](https://github.com/troupe-run/troupe/commit/1222e08981ebc1c06d978a5f200c5ff670b71726)), closes [#305](https://github.com/troupe-run/troupe/issues/305)
* **runner-ollama:** talk to Ollama and check what it requires ([#277](https://github.com/troupe-run/troupe/issues/277)) ([8893bae](https://github.com/troupe-run/troupe/commit/8893baef1b7a6055235fd1a0da79ea59f216d140))
* **runner-protocol:** a context event for content lost mid-run ([66a0127](https://github.com/troupe-run/troupe/commit/66a012776a1b8aa37ff544397b9d5096b6ef63ce))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** say when a retry wasn't safe ([0dda581](https://github.com/troupe-run/troupe/commit/0dda58103d34b1aece6cf01c9c8636776dd36168)), closes [#378](https://github.com/troupe-run/troupe/issues/378)
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runners:** remove the LM Studio runner before 0.2.0 ([26e9b7a](https://github.com/troupe-run/troupe/commit/26e9b7ac949237f3844a45513473525b63169b75))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **runtimes:** name runtimes in config and hand runs their credential ([5e14751](https://github.com/troupe-run/troupe/commit/5e14751ac70c364326dedd44a2e6b8c8186cb05c))
* **sdk:** check tool paths and declared effects ([3a38e7b](https://github.com/troupe-run/troupe/commit/3a38e7ba4a83a50efbca1799df79f2391b610345))
* **sdk:** require send_context to build an EventNumbering ([f172a1a](https://github.com/troupe-run/troupe/commit/f172a1a560b491fa4b5a974dcfb46b30f387c6e5))
* **sdk:** run a model's tool calls in the workspace ([e415af7](https://github.com/troupe-run/troupe/commit/e415af71dbbaf97e2a7e5c8cd8b362a60067a3f1))


### Bug Fixes

* **config:** never name the keys leading to a null in a value ([e6710ab](https://github.com/troupe-run/troupe/commit/e6710aba13d319f14e4922f2d629db9435753ba5))
* **config:** never repeat a value core refuses for its shape ([b5a95bd](https://github.com/troupe-run/troupe/commit/b5a95bd9155a76acc3953d42501d0800163f5288))
* **host:** parse a runner's line before masking it ([14245f6](https://github.com/troupe-run/troupe/commit/14245f620ae341248e1df7a7f961d6a2dbe992d0))
* **runner-protocol:** say usage.inputTokens leaves out cache tokens ([f6d80b5](https://github.com/troupe-run/troupe/commit/f6d80b50f51845773243bcf22ebbfadbbc985da5))
* **runners:** clean a tool call's id and OpenAI's non-stream body ([45ab433](https://github.com/troupe-run/troupe/commit/45ab433c4f9fd08ee3c0b2d8c21c5e4dd229381f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
* **sdk:** clean a tool call's input after parsing its JSON text ([276374b](https://github.com/troupe-run/troupe/commit/276374bbe1ae6218053f3347bcbae08c92647bd7))
* **sdk:** give a path outside scratch the same answer everywhere ([130b91e](https://github.com/troupe-run/troupe/commit/130b91e1812e535f70f4bae369d4fe2016386164))
* **sdk:** load only regular files of a bounded size ([c70a494](https://github.com/troupe-run/troupe/commit/c70a494d8de6b3146fe99e3b99fcfa1fde364959))
* **sdk:** never repeat an endpoint refused in run/start ([8619164](https://github.com/troupe-run/troupe/commit/8619164f89eaccaa594c0e9ada5b3eded280ebda))
* **sdk:** never search through a Windows junction out of the workspace ([855a3bf](https://github.com/troupe-run/troupe/commit/855a3bf5f22bfd42f86b1e8358b543c2d738b479))
* **sdk:** one context event per place; bound run_with_progress ([acea07a](https://github.com/troupe-run/troupe/commit/acea07aaa8a858f74b347c64fc1c2055540d01a1))
* **sdk:** refuse a credential a request header can't carry ([b691e3f](https://github.com/troupe-run/troupe/commit/b691e3fe59177461d02de09fed6fff85329b81d9))
* **sdk:** walk messages for lone surrogates without recursion ([79800e2](https://github.com/troupe-run/troupe/commit/79800e2da2777ce65cad058e86c2278cb461be6f))
</details>

<details><summary>troupe-stage-local: 0.2.0</summary>

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-stage-local-v0.1.0...troupe-stage-local-v0.2.0) (2026-11-20)


### Features

* audit every run's changes against its declared effects ([3f5e31e](https://github.com/troupe-run/troupe/commit/3f5e31e85ef2d2b4f421a75d4fd918cd7ee7ffb4))
</details>

<details><summary>troupe-store-text: 0.1.1</summary>

## [0.1.1](https://github.com/troupe-run/troupe/compare/troupe-store-text-v0.1.0...troupe-store-text-v0.1.1) (2026-11-20)


### Bug Fixes

* **store:** never reuse a notification id across an order rebuild ([24e817d](https://github.com/troupe-run/troupe/commit/24e817d5e19cf53fa08793b6c2b1f87dade2f3e8)), closes [#454](https://github.com/troupe-run/troupe/issues/454)
* **store:** read the order log as it is now before numbering events ([5292580](https://github.com/troupe-run/troupe/commit/52925800bf2db990755136a714c78d80c37da9d6))
* **store:** refuse a damaged local line on every read, not once ([1859332](https://github.com/troupe-run/troupe/commit/1859332c783a1ee1df45d9c008b4b66c28cf3110))
* **store:** tell listeners of an order by its last id, not its length ([afe6d27](https://github.com/troupe-run/troupe/commit/afe6d27b427dfa8aa8b173b4f5fbbadec79e4eb2))
</details>

<details><summary>troupe-vcs-files: 0.2.0</summary>

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-vcs-files-v0.1.0...troupe-vcs-files-v0.2.0) (2026-11-20)


### Features

* audit every run's changes against its declared effects ([3f5e31e](https://github.com/troupe-run/troupe/commit/3f5e31e85ef2d2b4f421a75d4fd918cd7ee7ffb4))
* **vcs:** say whether a directory is in a repository ([09abe93](https://github.com/troupe-run/troupe/commit/09abe93e078ef6635ab10a4e240ca79ddc6a852e))
</details>

<details><summary>troupe-vcs-git: 0.2.0</summary>

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-vcs-git-v0.1.0...troupe-vcs-git-v0.2.0) (2026-11-20)


### Features

* audit every run's changes against its declared effects ([3f5e31e](https://github.com/troupe-run/troupe/commit/3f5e31e85ef2d2b4f421a75d4fd918cd7ee7ffb4))
* **vcs:** say whether a directory is in a repository ([09abe93](https://github.com/troupe-run/troupe/commit/09abe93e078ef6635ab10a4e240ca79ddc6a852e))


### Bug Fixes

* **vcs-git:** stat the branch's ref before the read that names it ([b4a017b](https://github.com/troupe-run/troupe/commit/b4a017b8b201ecfcca84bb3d9d45e4ade1ddbc18))
* **vcs:** judge root names only as far as the walk needs them ([14e5c1a](https://github.com/troupe-run/troupe/commit/14e5c1a4eeaf57c6260b126509e42a4c47a2e406)), closes [#388](https://github.com/troupe-run/troupe/issues/388)
* **vcs:** name an unborn branch as git will once it's born ([f60d21d](https://github.com/troupe-run/troupe/commit/f60d21db6c4946bf32729219abc576f65dbc3e4b)), closes [#388](https://github.com/troupe-run/troupe/issues/388)
* **vcs:** watch refs sharing the branch's name in the token ([a2ab9cb](https://github.com/troupe-run/troupe/commit/a2ab9cba27ef32861ce224eff67e7224e05c1395))


### Performance Improvements

* **vcs-git:** re-read the branch and HEAD in one git process ([5f5420a](https://github.com/troupe-run/troupe/commit/5f5420a5ab0b1f1a06077cce4927a867cf47a77f))
</details>

<details><summary>troupe-runner-anthropic: 0.1.0</summary>

## 0.1.0 (2026-11-20)


### ⚠ BREAKING CHANGES

* **sdk:** EventNumbering requires send_context.

### Features

* **runner-anthropic:** add a runner for the Anthropic Messages API ([0d3bd99](https://github.com/troupe-run/troupe/commit/0d3bd995def2ce4d24be238614864170fb109465))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **sdk:** require send_context to build an EventNumbering ([f172a1a](https://github.com/troupe-run/troupe/commit/f172a1a560b491fa4b5a974dcfb46b30f387c6e5))


### Bug Fixes

* **anthropic:** read a streamed tool input's JSON as Unicode text ([1686d63](https://github.com/troupe-run/troupe/commit/1686d635d5d04616b8781281a1d850368b289051))
* **claude-code:** note a replaced surrogate in the effects server ([96bc001](https://github.com/troupe-run/troupe/commit/96bc00102f8478f4d7c0b528bf46716ff58e912b))
* **runner-anthropic:** answer the handshake before importing the library ([16574e8](https://github.com/troupe-run/troupe/commit/16574e8c755cb4ad8e5b1ade99c8d3ff3b9724b3))
* **runners:** read OpenAI's and Anthropic's error bodies as text ([d08fb59](https://github.com/troupe-run/troupe/commit/d08fb592feceb0e07dbd57c4b02f92493584055f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
</details>

<details><summary>troupe-runner-claude-code: 0.2.0</summary>

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-runner-claude-code-v0.1.0...troupe-runner-claude-code-v0.2.0) (2026-11-20)


### ⚠ BREAKING CHANGES

* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **claude-code:** a Claude Code run whose context fills now ends with an error result instead of compacting. A long run that got through by compacting fails until its task is split or its actor opts in ([#310](https://github.com/troupe-run/troupe/issues/310)).
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.

### Features

* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **claude-code:** capture fixtures through the runner's own rules ([2e25dce](https://github.com/troupe-run/troupe/commit/2e25dce0494625c266e59da14c113fb9c888f60d))
* **claude-code:** Claude Code compacts when the run says compact ([dbd05a2](https://github.com/troupe-run/troupe/commit/dbd05a2afb9e05d1dc4d9dcda811ccc26e77595e))
* **claude-code:** map Claude Code's context limit to context-length ([daa5baa](https://github.com/troupe-run/troupe/commit/daa5baa20c232941a42aefa9dd82b7788a9481f0))
* **claude-code:** translate declared effects into permission rules ([7ed5cf1](https://github.com/troupe-run/troupe/commit/7ed5cf1e6ec9596af2fafde03e392a6084546b46))
* **claude-code:** turn off Claude Code's automatic compaction ([d2524d0](https://github.com/troupe-run/troupe/commit/d2524d01cc119a4e15860559ba74b8a6d3e26548))
* **lm-studio:** stop at the context limit, and warn it won't compact ([a45df7b](https://github.com/troupe-run/troupe/commit/a45df7b2516f79aa9c7c11bcc439ebb10c1d6df6))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)


### Bug Fixes

* **claude-code:** note a replaced surrogate in the effects server ([96bc001](https://github.com/troupe-run/troupe/commit/96bc00102f8478f4d7c0b528bf46716ff58e912b))
* **runners:** clean a tool call's id and OpenAI's non-stream body ([45ab433](https://github.com/troupe-run/troupe/commit/45ab433c4f9fd08ee3c0b2d8c21c5e4dd229381f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
* **sdk:** walk messages for lone surrogates without recursion ([79800e2](https://github.com/troupe-run/troupe/commit/79800e2da2777ce65cad058e86c2278cb461be6f))
</details>

<details><summary>troupe-runner-mistralrs: 0.1.0</summary>

## 0.1.0 (2026-11-20)


### Features

* **init:** warm a runner's engine before its first run ([23662dc](https://github.com/troupe-run/troupe/commit/23662dc55a76e351ede838b9bdd1772b0d955062))
* **runner-mistralrs:** add the in-process runner's package and engine ([50518ab](https://github.com/troupe-run/troupe/commit/50518abcf64487da09a7a1f0131272e6e454915b))
* **runner-mistralrs:** run the conversation, with tests and docs ([096e135](https://github.com/troupe-run/troupe/commit/096e135cc0c099600146355d63cebab06d6c9daf))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)


### Bug Fixes

* **runner-mistralrs:** act on the review of [#422](https://github.com/troupe-run/troupe/issues/422) ([417a843](https://github.com/troupe-run/troupe/commit/417a843a5849cdc06d41d7533b28a75c828ee113))
* **runner-mistralrs:** check the answer comes before the load ([2f7e3e5](https://github.com/troupe-run/troupe/commit/2f7e3e5e4a71f6170938190a2ab729c106eebec2))
* **runner-mistralrs:** refuse a huge integer temperature as invalid ([55902b2](https://github.com/troupe-run/troupe/commit/55902b25132b3147c5713fd3c35af8aa8abba48e))
* **runners:** clean a tool call's id and OpenAI's non-stream body ([45ab433](https://github.com/troupe-run/troupe/commit/45ab433c4f9fd08ee3c0b2d8c21c5e4dd229381f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
</details>

<details><summary>troupe-runner-ollama: 0.1.0</summary>

## 0.1.0 (2026-11-20)


### ⚠ BREAKING CHANGES

* **runner-ollama:** troupe-run no longer installs the Ollama runner by default; install troupe-run[ollama] (or troupe-run[all]).
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* **ollama:** a run told to compact stubs old tool results to fit ([30a4a52](https://github.com/troupe-run/troupe/commit/30a4a52cbcff9203574fbeb1531d9317c49887c4))
* **ollama:** end the run with output-limit on a cut answer ([f8a4a86](https://github.com/troupe-run/troupe/commit/f8a4a86e04d4f62a364f58bfe26d789d3046f564))
* **openai:** a run told to compact stubs old outputs after a refusal ([43a2891](https://github.com/troupe-run/troupe/commit/43a28914cff30c7952889317356d09d851cb0047))
* **runner-ollama:** install the Ollama runner as troupe-run[ollama] ([0760a38](https://github.com/troupe-run/troupe/commit/0760a383bdb64680106cfa4fcb83d476cadbf875))
* **runner-ollama:** run troupe's own tool loop over /api/chat ([#277](https://github.com/troupe-run/troupe/issues/277)) ([e2ab0a1](https://github.com/troupe-run/troupe/commit/e2ab0a1572e0d7d1c8ab1c36bb22285cba3b98a0))
* **runner-ollama:** scaffold the plugin and check its options ([#277](https://github.com/troupe-run/troupe/issues/277)) ([0cba57a](https://github.com/troupe-run/troupe/commit/0cba57a88e5ef9a7482c9373c9ae843938b2bdd2))
* **runner-ollama:** take the endpoint and model from the runtime ([ff86f85](https://github.com/troupe-run/troupe/commit/ff86f85add2bbc545f1a47bb25f36595339c99d2)), closes [#289](https://github.com/troupe-run/troupe/issues/289)
* **runner-ollama:** talk to Ollama and check what it requires ([#277](https://github.com/troupe-run/troupe/issues/277)) ([8893bae](https://github.com/troupe-run/troupe/commit/8893baef1b7a6055235fd1a0da79ea59f216d140))
* **runner-ollama:** talk to Ollama through httpx2 ([6c64345](https://github.com/troupe-run/troupe/commit/6c6434522516868dda80b5aa5fe588bff7117fbf))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runners:** remove the LM Studio runner before 0.2.0 ([26e9b7a](https://github.com/troupe-run/troupe/commit/26e9b7ac949237f3844a45513473525b63169b75))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))


### Bug Fixes

* **config:** keep an old Ollama actor's endpoint in the move's fix ([903f817](https://github.com/troupe-run/troupe/commit/903f8170ab4929eeb82c9bc498b13abfb21aeb0c))
* **runner-ollama:** act on a review of the runner's code ([#277](https://github.com/troupe-run/troupe/issues/277)) ([746b227](https://github.com/troupe-run/troupe/commit/746b227b9bc17ba67e75dc7f5c366c4c1d556a1d))
* **runner-ollama:** count Ollama's cached prompt tokens apart ([292f732](https://github.com/troupe-run/troupe/commit/292f732c5926875ff5a7d8ac736c705513e76d86))
* **runner-ollama:** report cache reads only when every answer does ([fe89f99](https://github.com/troupe-run/troupe/commit/fe89f99e0847f1634fb50e09d47cbd211d97202f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
* **runtimes:** the actor's model beats TROUPE_RUNTIME_&lt;NAME&gt;_MODEL ([782d068](https://github.com/troupe-run/troupe/commit/782d068afe831a98ea6348e54d9a1b06023a76ec))
</details>

<details><summary>troupe-runner-openai: 0.1.0</summary>

## 0.1.0 (2026-11-20)


### ⚠ BREAKING CHANGES

* **openai:** the OpenAI runner is troupe-run's openai extra, no longer in the base install; install troupe-run[openai] or [all].
* **sdk:** EventNumbering requires send_context.
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* **config:** refuse an actor whose runner can't use its runtime ([ed15536](https://github.com/troupe-run/troupe/commit/ed1553634db7689202f6bd9bda6467aba1c89a5f))
* **openai:** a run told to compact stubs old outputs after a refusal ([43a2891](https://github.com/troupe-run/troupe/commit/43a28914cff30c7952889317356d09d851cb0047))
* **openai:** send the OpenAI runner's requests through openai ([3a732a3](https://github.com/troupe-run/troupe/commit/3a732a38830a9f934ca0941d9038e62fa689667c)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **plugin-sdk:** define what a credential's value may hold, once ([d97ce8f](https://github.com/troupe-run/troupe/commit/d97ce8f109d062215c690f93a8cffbf3e1b82516))
* **runner-openai:** estimate a run's cost from troupe's price ([5307f14](https://github.com/troupe-run/troupe/commit/5307f147e9aeb7e994ad8b7a655408c376edf9f1))
* **runner-openai:** rename to openai, ship it, and give it an audition ([f4cedac](https://github.com/troupe-run/troupe/commit/f4cedac9f3ce3e90af0b397c62a4910be6f3b997))
* **runner-openai:** speak the Responses API ([321699d](https://github.com/troupe-run/troupe/commit/321699d2f67e2cc2c51f530b9bd1a1406521661d))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **runtimes:** refuse a credential holding whitespace in core ([cac94eb](https://github.com/troupe-run/troupe/commit/cac94ebbed4a886a4aaf4119b16c5e9f9a015df9))
* **sdk:** require send_context to build an EventNumbering ([f172a1a](https://github.com/troupe-run/troupe/commit/f172a1a560b491fa4b5a974dcfb46b30f387c6e5))


### Bug Fixes

* **claude-code:** note a replaced surrogate in the effects server ([96bc001](https://github.com/troupe-run/troupe/commit/96bc00102f8478f4d7c0b528bf46716ff58e912b))
* **openai:** keep an encoded error's status; close events at once ([de5b095](https://github.com/troupe-run/troupe/commit/de5b0958e6ee07a4895371fbef37587a225d623e)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **openai:** keep requests below an endpoint whose path is // ([1f85a18](https://github.com/troupe-run/troupe/commit/1f85a18fb7ed4d4ea54bd0081d9067581bcf98da))
* **openai:** load the openai package only after run/start ([8ca2770](https://github.com/troupe-run/troupe/commit/8ca27705a3dc3e42dd66491b1db304c96380709a)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **openai:** refuse an encoded response the line cap can't count ([e87bcc8](https://github.com/troupe-run/troupe/commit/e87bcc8dc8a76e2be5765c3cffcbb25e5c5e5c2c)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **openai:** send only the headers a request needs ([1102fb0](https://github.com/troupe-run/troupe/commit/1102fb061e1695e45a8f1796778edbf52b3687b9)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **openai:** stop reading a whole body at ERROR_BODY_MAX_BYTES ([e646c37](https://github.com/troupe-run/troupe/commit/e646c379567b31f2e410d84b8d90719608832bd7)), closes [#331](https://github.com/troupe-run/troupe/issues/331)
* **runner-openai:** act on an independent review of unread files ([a00c1aa](https://github.com/troupe-run/troupe/commit/a00c1aa509c357ac3a662e92b3cd61a4f181ef22))
* **runner-openai:** act on the split review of the whole PR ([b3f1910](https://github.com/troupe-run/troupe/commit/b3f191015083b66515900bed2018bbdaa15e3428))
* **runner-openai:** end a refusal's service message as a sentence ([a329597](https://github.com/troupe-run/troupe/commit/a32959712b8cee9deeb222b60358018bac878418))
* **runner-openai:** end the run on a response in the wrong shape ([971654b](https://github.com/troupe-run/troupe/commit/971654b82b1a258a3aedd651abb7b1e10aeaf24e))
* **runner-openai:** report cache reads only when every response does ([f86b79e](https://github.com/troupe-run/troupe/commit/f86b79e51b86e27e3f47641203be03ff8efc8bf3))
* **runner-protocol:** act on the slice reviews of record kinds ([87d51d8](https://github.com/troupe-run/troupe/commit/87d51d83149f7547852f81721a84a2e9d627daef)), closes [#294](https://github.com/troupe-run/troupe/issues/294)
* **runners:** clean a tool call's id and OpenAI's non-stream body ([45ab433](https://github.com/troupe-run/troupe/commit/45ab433c4f9fd08ee3c0b2d8c21c5e4dd229381f))
* **runners:** read OpenAI's and Anthropic's error bodies as text ([d08fb59](https://github.com/troupe-run/troupe/commit/d08fb592feceb0e07dbd57c4b02f92493584055f))
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
* **runtimes:** count // as a path, as the Ollama runner does ([9be390c](https://github.com/troupe-run/troupe/commit/9be390c3d293df4d64b9a282df9746347a6e6f38))
* **sdk:** never repeat an endpoint refused in run/start ([8619164](https://github.com/troupe-run/troupe/commit/8619164f89eaccaa594c0e9ada5b3eded280ebda))
* **sdk:** refuse a credential a request header can't carry ([b691e3f](https://github.com/troupe-run/troupe/commit/b691e3fe59177461d02de09fed6fff85329b81d9))
</details>

<details><summary>troupe-runner-scripted: 0.2.0</summary>

## [0.2.0](https://github.com/troupe-run/troupe/compare/troupe-runner-scripted-v0.1.0...troupe-runner-scripted-v0.2.0) (2026-11-20)


### ⚠ BREAKING CHANGES

* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **runner-protocol:** say when a retry wasn't safe
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **protocol:** estimate a run's cost from a price troupe resolves ([b809b61](https://github.com/troupe-run/troupe/commit/b809b61b451cd5aeac6154eaa0cd16ab8f5b4ba9))
* **runner-protocol:** a context event for content lost mid-run ([66a0127](https://github.com/troupe-run/troupe/commit/66a012776a1b8aa37ff544397b9d5096b6ef63ce))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** say when a retry wasn't safe ([0dda581](https://github.com/troupe-run/troupe/commit/0dda58103d34b1aece6cf01c9c8636776dd36168)), closes [#378](https://github.com/troupe-run/troupe/issues/378)
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** end every runner through the SDK's exit_now, so coverage can save ([217e083](https://github.com/troupe-run/troupe/commit/217e083b5bc9d36dea3b2ccc84277e9e20889b9a)), closes [#443](https://github.com/troupe-run/troupe/issues/443)
* **runtimes:** name runtimes in config and hand runs their credential ([5e14751](https://github.com/troupe-run/troupe/commit/5e14751ac70c364326dedd44a2e6b8c8186cb05c))
* **scripted:** a tool step that runs calls through the SDK's tools ([949996a](https://github.com/troupe-run/troupe/commit/949996a22aeaa537ab821abebb752af75c74c5d5))


### Bug Fixes

* **runner-protocol:** act on the slice reviews of record kinds ([87d51d8](https://github.com/troupe-run/troupe/commit/87d51d83149f7547852f81721a84a2e9d627daef)), closes [#294](https://github.com/troupe-run/troupe/issues/294)
* **runners:** record each lone surrogate replaced, in a context event ([ae9f7a6](https://github.com/troupe-run/troupe/commit/ae9f7a6f3abe27c9d7863c1f5c56a38b23a64cea))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runners:** write lone surrogates as U+FFFD, never as an escape ([fef4bd5](https://github.com/troupe-run/troupe/commit/fef4bd5c222b1c13014b8e14bf3692d130624d83))
</details>

<details><summary>protocol: 0.2.0</summary>

## [0.2.0](https://github.com/troupe-run/troupe/compare/protocol-v0.1.0...protocol-v0.2.0) (2026-11-20)


### ⚠ BREAKING CHANGES

* **runs:** Run.Started requires on_context_full, so a run started before this no longer reads. There are no theatres to migrate.
* **runner-protocol:** a runner that predates this rejects run/start's new onContextFull field. The contract is version 0, and every runner is in this repository.
* **protocol:** a run that hasn't ended has nothing from its end
* **runner-protocol:** say when a retry wasn't safe
* **protocol:** records and messages that leave out these fields, or hold runner_reported or a start's clones, no longer validate.
* **runner-protocol:** a runner's result with status error must carry a reason from the contract's list, and an ok result must not; troupe refuses either as a protocol violation, and run.error-result's details now require the reason. Every runner that speaks the contract is in this repository and is updated here; there are no recorded theatres to migrate.
* **runner-protocol:** a Run.Ended outcome with a transcript but no transcriptFormat no longer validates, so ends recorded before this change don't read back (pre-1.0: there are no theatres in use). the OpenAI runner's transcript records are the bytes themselves with the contract's kinds, not its own JSON objects with kind request, response, stream, body or dropped, and the request URL is no longer recorded.

### Features

* audit every run's changes against its declared effects ([3f5e31e](https://github.com/troupe-run/troupe/commit/3f5e31e85ef2d2b4f421a75d4fd918cd7ee7ffb4))
* carry declared effects and a scratch directory to runners ([ce62005](https://github.com/troupe-run/troupe/commit/ce6200565f60b7a1b6661f2061aa7994cedb7d86))
* **cli:** init names the extra an audition's runner comes with ([7083013](https://github.com/troupe-run/troupe/commit/7083013781cf477f1468320815391c46ca3b32cd)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **cli:** troupe init, and init --audition for an example actor ([fc34264](https://github.com/troupe-run/troupe/commit/fc342642ac4ec34ef08369688b925cbda3c00fcf))
* **config:** read and show config paths with brackets for any key ([d2e2bd6](https://github.com/troupe-run/troupe/commit/d2e2bd65fee97daeed93afa8eb380766fcbeffcf))
* **init:** warm a runner's engine before its first run ([23662dc](https://github.com/troupe-run/troupe/commit/23662dc55a76e351ede838b9bdd1772b0d955062))
* **protocol:** a run that hasn't ended has nothing from its end ([81db7f0](https://github.com/troupe-run/troupe/commit/81db7f054e201428a9fbd649a129022fa7b0eba9)), closes [#313](https://github.com/troupe-run/troupe/issues/313)
* **protocol:** estimate a run's cost from a price troupe resolves ([b809b61](https://github.com/troupe-run/troupe/commit/b809b61b451cd5aeac6154eaa0cd16ab8f5b4ba9))
* **protocol:** refuse a runner that isn't installed, naming its extra ([a81a3fb](https://github.com/troupe-run/troupe/commit/a81a3fb2b9c13478c763cc93ea9995648d9a40d4)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **protocol:** require the fields troupe always writes ([1222e08](https://github.com/troupe-run/troupe/commit/1222e08981ebc1c06d978a5f200c5ff670b71726)), closes [#305](https://github.com/troupe-run/troupe/issues/305)
* **runner-anthropic:** add a runner for the Anthropic Messages API ([0d3bd99](https://github.com/troupe-run/troupe/commit/0d3bd995def2ce4d24be238614864170fb109465))
* **runner-ollama:** talk to Ollama and check what it requires ([#277](https://github.com/troupe-run/troupe/issues/277)) ([8893bae](https://github.com/troupe-run/troupe/commit/8893baef1b7a6055235fd1a0da79ea59f216d140))
* **runner-protocol:** a context event for content lost mid-run ([66a0127](https://github.com/troupe-run/troupe/commit/66a012776a1b8aa37ff544397b9d5096b6ef63ce))
* **runner-protocol:** a failed result says why, in a reason ([3dcfe3f](https://github.com/troupe-run/troupe/commit/3dcfe3f344d1621109761bedbe5eda5ed773b5a7)), closes [#296](https://github.com/troupe-run/troupe/issues/296)
* **runner-protocol:** report the model that served a run ([409a5f9](https://github.com/troupe-run/troupe/commit/409a5f9c82361e8134d88816010d98e47419defc)), closes [#295](https://github.com/troupe-run/troupe/issues/295)
* **runner-protocol:** run/start says whether the run may compact ([21851c3](https://github.com/troupe-run/troupe/commit/21851c36e6b9e74a5cf7715325580119fe6b8cf1))
* **runner-protocol:** say when a retry wasn't safe ([0dda581](https://github.com/troupe-run/troupe/commit/0dda58103d34b1aece6cf01c9c8636776dd36168)), closes [#378](https://github.com/troupe-run/troupe/issues/378)
* **runner-protocol:** transcript records can say what kind they are ([a0c3fd4](https://github.com/troupe-run/troupe/commit/a0c3fd4d6b13778e4c47833e2cf2c4f062ada922))
* **runners:** remove the LM Studio runner before 0.2.0 ([26e9b7a](https://github.com/troupe-run/troupe/commit/26e9b7ac949237f3844a45513473525b63169b75))
* **runs:** actors opt in to compaction; policy can allow or forbid it ([27c8f6f](https://github.com/troupe-run/troupe/commit/27c8f6f53ddef172961180fd8f7db8bf2096253a))
* **runs:** audit every started run and record what it found ([ac99c89](https://github.com/troupe-run/troupe/commit/ac99c8938a494fff2f14bfa89dfd708e67427107))
* **runs:** keep the notices a run raises in its history ([2ceae43](https://github.com/troupe-run/troupe/commit/2ceae432c1934a15318e88b6d60832b8a00bca23))
* **runs:** perform runs the Ollama runner by name ([#277](https://github.com/troupe-run/troupe/issues/277)) ([d50be0c](https://github.com/troupe-run/troupe/commit/d50be0c411cf9b1d87510e17ca8f403de6769e79))
* **runs:** refuse a runtime the environment makes unfit for its runner ([f722217](https://github.com/troupe-run/troupe/commit/f7222172dd2c68925dd8d9d6d8da55e2637fb253))
* **runtimes:** add an in-process runtime with no endpoint ([3e9ecbd](https://github.com/troupe-run/troupe/commit/3e9ecbdd7e34458cccb6b620b02ae68f87bf6411))
* **runtimes:** fit a built-in runtime only to the runner it's for ([6e1df8e](https://github.com/troupe-run/troupe/commit/6e1df8e385a45ccd027aafeccfe235b5d96327b5)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runtimes:** judge the lm-studio runner's fit, https included ([4f07f83](https://github.com/troupe-run/troupe/commit/4f07f836c03c1ee890288d3f7d49b8e0d1b5ad70)), closes [#291](https://github.com/troupe-run/troupe/issues/291)
* **runtimes:** name runtimes in config and hand runs their credential ([5e14751](https://github.com/troupe-run/troupe/commit/5e14751ac70c364326dedd44a2e6b8c8186cb05c))
* **runtimes:** refuse a credential holding whitespace in core ([cac94eb](https://github.com/troupe-run/troupe/commit/cac94ebbed4a886a4aaf4119b16c5e9f9a015df9))
* **vcs:** say whether a directory is in a repository ([09abe93](https://github.com/troupe-run/troupe/commit/09abe93e078ef6635ab10a4e240ca79ddc6a852e))


### Bug Fixes

* act on the review of [#338](https://github.com/troupe-run/troupe/issues/338) ([76457e4](https://github.com/troupe-run/troupe/commit/76457e4de9fa3327d1cf5093e0aa532e85eac35a)), closes [#333](https://github.com/troupe-run/troupe/issues/333)
* **cli:** never repeat a value config set can't type ([cf16bd2](https://github.com/troupe-run/troupe/commit/cf16bd270562c5129525a5812d37a288f05ff1c0))
* **config:** cut a malformed path at a bracket it failed in ([fd47af2](https://github.com/troupe-run/troupe/commit/fd47af2e8df512dbf180f765bb8980a43f183db9))
* **config:** price a model whose name holds a dot in brackets ([3a77deb](https://github.com/troupe-run/troupe/commit/3a77deb1891beb00eb7749077de96b5046efbc6c))
* **config:** show a credential name from the environment by its setter ([7924383](https://github.com/troupe-run/troupe/commit/7924383dd0c43ada4dbdf7a9ac73a0e6797e976a))
* **protocol:** say a malformed path's offset can pass its text ([77a0825](https://github.com/troupe-run/troupe/commit/77a08258a830b5daff9abc6fddd0153174ed187e))
* **protocol:** say what the actor schema's $schema holds ([2894f36](https://github.com/troupe-run/troupe/commit/2894f3617b2c061ce2f8be684f14d97404e88f6c))
* **runner-mistralrs:** act on the review of [#422](https://github.com/troupe-run/troupe/issues/422) ([417a843](https://github.com/troupe-run/troupe/commit/417a843a5849cdc06d41d7533b28a75c828ee113))
* **runner-protocol:** act on the slice reviews of record kinds ([87d51d8](https://github.com/troupe-run/troupe/commit/87d51d83149f7547852f81721a84a2e9d627daef)), closes [#294](https://github.com/troupe-run/troupe/issues/294)
* **runner-protocol:** say a retry can name five reasons ([723516f](https://github.com/troupe-run/troupe/commit/723516f2c7fec4bbc7cc881325471e642cb160e5))
* **runner-protocol:** say usage.inputTokens leaves out cache tokens ([f6d80b5](https://github.com/troupe-run/troupe/commit/f6d80b50f51845773243bcf22ebbfadbbc985da5))
* **runners:** refuse a second initialize with already-initialized ([ad1769b](https://github.com/troupe-run/troupe/commit/ad1769bd880fbb996b1fc94fafcfdd7aad89923e))
* **runs:** drop an unpriced cost estimate with a notice, not a crash ([a6fa0d2](https://github.com/troupe-run/troupe/commit/a6fa0d23630513d904aca5b93d55dae97f3edd39))
* **runs:** store a dropped estimate's oversized result as a message ([0c11825](https://github.com/troupe-run/troupe/commit/0c11825a6208e270882e61821ab2557f0b2a2207))
* **runtimes:** never echo a refused runtime variable's value ([610096d](https://github.com/troupe-run/troupe/commit/610096d9e03d08379a6db6c81e1928f1343beba7))
* **runtimes:** never repeat a credential's variable name from the env ([0cabf18](https://github.com/troupe-run/troupe/commit/0cabf18e98fd6ed23863a983658652a79fbd6bfb))
* **runtimes:** the actor's model beats TROUPE_RUNTIME_&lt;NAME&gt;_MODEL ([782d068](https://github.com/troupe-run/troupe/commit/782d068afe831a98ea6348e54d9a1b06023a76ec))
* **store:** read the order log as it is now before numbering events ([5292580](https://github.com/troupe-run/troupe/commit/52925800bf2db990755136a714c78d80c37da9d6))
* **vcs:** name an unborn branch as git will once it's born ([f60d21d](https://github.com/troupe-run/troupe/commit/f60d21db6c4946bf32729219abc576f65dbc3e4b)), closes [#388](https://github.com/troupe-run/troupe/issues/388)
</details>

---
This PR was generated with [Release Please](https://github.com/googleapis/release-please). See [documentation](https://github.com/googleapis/release-please#release-please).