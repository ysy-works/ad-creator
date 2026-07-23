import { app } from "../../scripts/app.js";

function applyHiddenMetadata(node) {
  let changed = false;
  for (const widget of node.widgets ?? []) {
    if (!widget.options?.hidden) continue;
    widget.hidden = true;
    widget.computeSize = () => [0, -4];
    changed = true;
  }

  for (const input of node.inputs ?? []) {
    if (!input.hidden) continue;
    input.shape = 0;
    changed = true;
  }

  if (changed) {
    node.setSize?.(node.computeSize());
    node.graph?.setDirtyCanvas?.(true, true);
  }
}

app.registerExtension({
  name: "ad_creator.feature_visibility",
  async nodeCreated(node) {
    if (
      node.comfyClass !== "AD_BuildGenerationRequest" &&
      node.type !== "AD_BuildGenerationRequest"
    ) {
      return;
    }
    applyHiddenMetadata(node);
  },
});
