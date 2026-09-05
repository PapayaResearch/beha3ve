// Edit descriptions opened by the question-mark buttons and outcome explanations here.
const viewerCopy = {
  tooltips: {
    experiment: "Choose an experiment to inspect its episodes.",
    pair: "Choose a single episode, a control/treatment pair, or a factorial comparison differing in one factor. Comparisons are matched by task and seed.",
    theme: "Use Light or Dark, or choose System to follow your device's appearance automatically.",
    steps: "Select an action number to inspect the observation delivered before it. Unlink steps to navigate each episode separately. Arrow keys move both episodes when linked, or the arm selected under Browse when unlinked. Linking again uses that arm's step number for both episodes.",
    paired: "Control and treatment are shown at the same ordinal action. Their actions may have different meanings or targets.",
    unequal: "One episode has ended. Continue through the longer episode or select an earlier action to compare both.",
    comparison: "The observations, actions, or applied interventions differ at this step. Compare the two panes to inspect the difference.",
    action: "The action submitted by the agent, including its arguments and any answer text.",
    model: "Model name, response identifier, token counts, and request latency. Reasoning tokens are part of output usage, not an extra amount to add. Missing counts mean the provider did not report them.",
    interventions: "Changes applied by the experiment at this step, with the affected fields and application order.",
    environment: "Additional information returned by the environment for this transition.",
    messages: "The recorded model request, returned reasoning when available, raw output, and parsed response. Legacy requests may have been shortened by the viewer; new requests are shown as recorded.",
    outcomes: "Results measured after the complete episode, regardless of which step is selected. Control and treatment values appear on the same row.",
    unknownOutcome: "This is a value reported by the task evaluator. Its scale and meaning depend on the task definition.",
    maximize: "Higher values count as better performance for this measure.",
    minimize: "Lower values count as better performance for this measure.",
    report: "This measure describes behavior; neither a higher nor a lower value is designated as better."
  },
  directions: {
    maximize: "Higher is better",
    minimize: "Lower is better",
    report: "Descriptive"
  },
  outcomes: {
    cart_choice: { label: "Product selected", detail: "The product in the cart at the end of the episode. Candidate numbers start at 1 when no name is recorded." },
    valid_choice: { label: "Valid product choice", detail: "Exactly one of the candidate products was in the cart." },
    target_chosen: { label: "Target product selected", detail: "Whether the cart contained the experiment's target product. Recorded 1 means selected; 0 means not selected." },
    inspected_both: { label: "Both products inspected", detail: "Both candidate pages were observed before an item was added to the cart." },
    action_count: { label: "Actions taken", detail: "Total actions in the episode." },
    success: { label: "Task completed successfully", detail: "The task evaluator's final success result." },
    terminated: { label: "Episode ended", detail: "Whether the environment reported termination. This does not establish task success." },
    osworld_score: { label: "OSWorld score", detail: "Score reported by the OSWorld evaluator; interpretation depends on the task's evaluator." },
    pages_visited: { label: "Pages visited", detail: "Number of entries in the recorded page history." }
  }
};
