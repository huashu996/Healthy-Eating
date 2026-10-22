import ts from 'typescript-eslint';
import globals from 'globals';
export default ts.config({ignores:['dist/**','node_modules/**','test-results/**']}, ...ts.configs.recommended, {languageOptions:{globals:{...globals.browser,...globals.node}},rules:{'@typescript-eslint/no-explicit-any':'off'}});
