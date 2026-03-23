/** Conventional commits — enforced in CI via wagoid/commitlint-github-action. */
export default {
  extends: ["@commitlint/config-conventional"],
  ignores: [
    (message) =>
      /^Merge (pull request|branch|remote-tracking branch) /m.test(message),
  ],
};
