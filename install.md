# インストールと外部リポジトリへの保存

GitHubのユーザー名から活動草マップを生成し、自分のプロフィールリポジトリなどの専用ブランチへ毎月保存できます。
生成用リポジトリへの保存は、外部保存の指定にかかわらず実行します。<br>
外部保存を指定した場合は、生成用リポジトリと指定先リポジトリの両方へ保存します。

|外部保存の設定|生成用リポジトリ|指定先リポジトリ|
|---|---|---|
|指定なし（3項目とも未設定）|`contribution-graphs`へ保存|保存しない|
|指定あり（3項目とも設定済み）|`contribution-graphs`へ保存|`DEPLOY_REPOSITORY`の`DEPLOY_BRANCH`へ保存|


## 1. 生成用リポジトリを作る

[Use this template](https://github.com/DaisukeDaisuke/github-contribution/generate)から生成用リポジトリを作成します。既に作成済みなら、そのリポジトリを使います。
生成対象のユーザー名は既定で生成用リポジトリの所有者です。開始年はそのユーザーのアカウント作成年、終了日は実行日から自動判定します。

<img width="839" height="763" alt="image" src="https://github.com/user-attachments/assets/72fc725f-5d97-4ca8-99b2-e4ab4e53897d" />

## 2. 保存先とブランチを決める

プロフィールREADMEから同じリポジトリ内の画像を参照する例です。

|項目|設定例|
|---|---|
|生成用リポジトリ|`DaisukeDaisuke/github-contribution`|
|保存先リポジトリ|`DaisukeDaisuke/DaisukeDaisuke`|
|保存先ブランチ|`contribution-graphs`|

保存先リポジトリはあらかじめ作成します。<br>
保存先ブランチが未作成なら、Actionsが既定ブランチの内容・履歴を引き継がずに作成します。
保存先の実際の既定ブランチには、マークファイルがあってもpushしません。既定ブランチ名をAPIで確認し、push直前にも再確認します。

## 3. 保存先へ書き込めるトークンを作る

個人設定の**Settings → Developer settings → Personal access tokens → Fine-grained tokens**でトークンを作成します。
**Resource owner**に保存先の所有者、**Repository access → Only select repositories**に保存先リポジトリを指定します。**Repository permissions → Contents**を**Read and write**にします。**Metadata: Read-only**も必要です。
このトークンは指定先への保存だけに使います。生成用リポジトリへの保存は従来どおりActions標準の`github.token`を使うため、`DEPLOY_TOKEN`に生成用リポジトリへのアクセス権限を追加する必要はありません。

## 4. 生成用リポジトリに設定する

### Variables：保存先を登録

**Variablesには`DEPLOY_REPOSITORY`と`DEPLOY_BRANCH`だけを登録します。トークンは登録しません。**<br>

自分の生成用リポジトリでは、`<user>`を所有者名へ置き換えて開きます。リポジトリ名を変更した場合は`github-contribution`も変更してください。

```text
https://github.com/<user>/github-contribution/settings/variables/actions
```

<img width="950" height="636" alt="image" src="https://github.com/user-attachments/assets/cd9e08bf-9908-4a45-9bdb-9b3ebc08038a" />


**Variables → New repository variable**で次の2つを登録します。

|名前|値の例|意味|
|---|---|---|
|`DEPLOY_REPOSITORY`|`DaisukeDaisuke/DaisukeDaisuke`|保存先。URLではなく`所有者/リポジトリ名`|
|`DEPLOY_BRANCH`|`contribution-graphs`|保存先の専用ブランチ名|

<img width="957" height="559" alt="image" src="https://github.com/user-attachments/assets/34d3fabc-9d33-417c-bcf2-bfbfb81c41be" />

<img width="965" height="655" alt="image" src="https://github.com/user-attachments/assets/550031ad-934c-433e-a373-bc6ccd055bf7" />


### Secrets：DEPLOY_TOKENを登録

**`DEPLOY_TOKEN`は必ずRepository secretに登録します。**<br>
トークンの値をVariables・README・コード・URLへ記載しないでください。<br>

```text
https://github.com/<user>/github-contribution/settings/secrets/actions
```

**Secrets → New repository secret**で次を登録します。

|名前|値|
|---|---|
|`DEPLOY_TOKEN`|手順3で作成したトークン|

Actionsは`${{ secrets.DEPLOY_TOKEN }}`からトークンを受け取り、トークンの値をログへ出力せず、リモートURL・コマンド引数・Git設定ファイルにも保存しません。
失敗時はGitの標準エラーと標準出力を表示します。トークン本体・URL内の認証情報・Authorizationヘッダー・認証に使うBase64値を伏せたうえで、拒否理由と終了コードを残します。

3項目とも未設定なら生成用リポジトリだけ、3項目とも設定済みなら両方のリポジトリを更新します。<br>
一部だけ設定されている場合は、設定不足として停止します。

<img width="802" height="819" alt="image" src="https://github.com/user-attachments/assets/8a4ab7d1-884d-4f2c-8083-d16ba58a277e" />


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

生成用リポジトリの**Actions → Update contribution archive → Run workflow**を実行します。<br>
生成用リポジトリの`contribution-graphs`へSVG・PNG・WebP・HTML・CSV・JSONを保存します。外部保存も指定していれば、同じ生成物を指定先にも保存し、指定先のブランチには`.contribution-map`も作成します。
ヘッダーの`xx days`は、取得期間内に活動が1件以上あった日数の合計です。
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


## 活動統計の画像

追加のシークレットは不要です。草画像と同じ対象ユーザーを、Actions標準のトークンで集計します。`DEPLOY_TOKEN`は従来どおり外部デプロイ専用です。

`activity-dark.webp` / `activity-light.webp`が全体画像、`activity-dark3.webp` / `activity-light3.webp`が高さ600pxのフェード付きプレビューです。SVGとPNGも生成します。草画像の生成処理は変更しません。

同じリポジトリのREADMEから、別ブランチのプレビューをクリックして全体画像を開けます。外部デプロイの場合は`contribution-graphs`を保存先ブランチに置き換えます。生成先の`embed.md`とActions概要にも、保存先に合わせた画像とコピー用コードを表示します。

```markdown
[![activity-dark.webp](../contribution-graphs/activity-dark3.webp#gh-dark-mode-only)](../contribution-graphs/activity-dark.webp#gh-dark-mode-only) \
[![activity-light.webp](../contribution-graphs/activity-light3.webp#gh-light-mode-only)](../contribution-graphs/activity-light.webp#gh-light-mode-only)
```

活動統計の入力はActionsキャッシュだけに保存します。キャッシュキーはユーザー名とUTCのISO週（年＋週番号）です。同じ週は再取得せず、週が変わったら更新します。画像には取得日を表示します。API応答やキャッシュJSONを画像ブランチへコピーしません。既存の草マップ用CSV・JSONの出力設定はそのままです。
