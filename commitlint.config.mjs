export default {
  extends: ['@commitlint/config-conventional'],
  ignores: [
    (message) => message.startsWith('Merge '),
    (message) => /^chore\(changelog\):/i.test(message),
  ],
};
