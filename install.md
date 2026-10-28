# インストールと外部リポジトリへの保存
GitHubのユーザー名から活動草マップを生成し、自分のプロフィールリポジトリなどの専用ブランチへ毎月保存できます。
![profile-dark.webp](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-dark.webp#gh-dark-mode-only) \
![profile-light.webp](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-light.webp#gh-light-mode-only)
## 1. 生成用リポジトリを作る
[Use this template](https://github.com/DaisukeDaisuke/github-contribution/generate)から生成用リポジトリを作成します。既に作成済みなら、そのリポジトリを使います。
生成対象のユーザー名は既定で生成用リポジトリの所有者です。開始年はそのユーザーのアカウント作成年、終了日は実行日から自動判定します。
## 2. 保存先とブランチを決める
プロフィールREADMEから同じリポジトリ内の画像を参照する例です。
|項目|設定例|
|---|---|
|生成用リポジトリ|`DaisukeDaisuke/github-contribution`|
|保存先リポジトリ|`DaisukeDaisuke/DaisukeDaisuke`|
|保存先ブランチ|`contribution-graphs`|
保存先リポジトリはあらかじめ作成します。保存先ブランチが未作成なら、Actionsが既定ブランチの内容・履歴を引き継がずに作成します。
保存先の実際の既定ブランチには、マークファイルがあってもpushしません。既定ブランチ名をAPIで確認し、push直前にも再確認します。
## 3. 保存先へ書き込めるトークンを作る
個人設定の**Settings → Developer settings → Personal access tokens → Fine-grained tokens**でトークンを作成します。
**Resource owner**に保存先の所有者、**Repository access → Only select repositories**に保存先リポジトリを指定します。**Repository permissions → Contents**を**Read and write**にします。**Metadata: Read-only**も必要です。
## 4. 生成用リポジトリに設定する
**生成用リポジトリ**の**Settings → Secrets and variables → Actions**を開きます。
**Variables → New repository variable**で次の2つを登録します。
|名前|値の例|意味|
|---|---|---|
|`DEPLOY_REPOSITORY`|`DaisukeDaisuke/DaisukeDaisuke`|保存先。URLではなく`所有者/リポジトリ名`|
|`DEPLOY_BRANCH`|`contribution-graphs`|保存先の専用ブランチ名|
**Secrets → New repository secret**で次を登録します。
|名前|値|
|---|---|
|`DEPLOY_TOKEN`|手順3で作成したトークン|
3項目がすべて未設定なら、外部保存は実行せず、生成用リポジトリ内の`contribution-graphs`だけを更新します。一部だけ設定されている場合は、設定不足として停止します。
## 5. マークファイルの条件
マークファイル名は、保存先ブランチのルートに置く`.contribution-map`です。通常のファイルとして存在することを確認します。内容は空でも構いません。フォルダーやシンボリックリンクでは許可しません。
|保存先の状態|動作|
|---|---|
|既定ブランチ|常に拒否|
|ブランチが存在しない|独立した履歴で作成し、生成物とマークファイルを保存|
|ブランチが存在し、マークファイルがある|既存の履歴を保持して通常のコミット・pushで更新|
|ブランチが存在し、マークファイルがない|pushせず停止|
新規ブランチのマークファイルは自動で作成され、翌月以降の更新にも使われます。既存ブランチを使う場合は、そのブランチを生成物専用にしてからマークファイルを追加してください。
マーク済みブランチのファイルは生成物とマークファイルに揃えます。古いファイルや既定ブランチから持ち込まれたファイルは削除し、過去のコミット履歴は保持します。force pushは使いません。準備中に保存先ブランチが更新されていた場合は、自動再試行せず停止します。
## 6. 実行する
生成用リポジトリの**Actions → Update contribution archive → Run workflow**を実行します。完了すると、保存先ブランチにSVG・PNG・WebP・HTML・CSV・JSONと`.contribution-map`が保存されます。
以後は毎月1日09:17 JSTに更新します。フェード版の`profile-dark3`と`profile-light3`も生成を続けます。
## 7. プロフィールREADMEに貼る
保存先がプロフィールリポジトリで、ブランチが`contribution-graphs`なら、そのリポジトリのREADMEに次を貼り付けます。
```markdown
![profile-dark.webp](/../contribution-graphs/profile-dark.webp#gh-dark-mode-only) \
![profile-light.webp](/../contribution-graphs/profile-light.webp#gh-light-mode-only)
```
別のブランチ名を設定した場合は、上の`contribution-graphs`をその名前に変更します。保存先の`embed.md`にも、実際の設定に合わせた貼り付け用コードを出力します。
この相対パスは同じリポジトリ内での参照方法です。画像配信のレート制限を無くすものではありません。
## Pagesとして公開する場合
保存先の**Settings → Pages → Build and deployment → Source**を**Deploy from a branch**にし、保存先ブランチと`/(root)`を指定します。READMEで画像を参照するだけなら、この設定は不要です。
## 停止した場合
|原因|確認すること|
|---|---|
|設定不足|2つのVariablesと`DEPLOY_TOKEN`を同じ生成用リポジトリへ登録したか|
|既定ブランチへの保存|`DEPLOY_BRANCH`を専用ブランチ名に変更したか|
|マークファイルなし|保存先ブランチのルートに通常の`.contribution-map`があるか|
|認証・pushエラー|トークンの期限、保存先の選択、Contents権限、ブランチ保護|
|保存先が更新された|他の更新が完了してからRun workflowを再実行|
