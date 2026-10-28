# GitHub Contribution Archive
GitHubのユーザー名から、2016年以降の活動草マップをSVG・HTMLで生成するテンプレートです。全年の草マップをひとつの連続した表へ結合し、左側に年、右側に曜日を表示します。52週で折り返した帯を新しい順に上から配置し、最新年が一番上になります。帯の中は左から右へ週が進み、年末ではリセットしません。日別件数・GitHub本来の濃淡と集計データを保持します。
## 初回設定
この一式をGitHubのリポジトリへ配置します。テンプレートとして配布する場合は、そのリポジトリのSettings → General → Template repositoryを有効にしてください。利用者はUse this template → Create a new repositoryから自分のリポジトリを作れます。
作成したリポジトリのActionsタブでUpdate contribution archiveを選び、Run workflowを実行してください。コード内のユーザー名を書き換える必要はありません。対象は既定でリポジトリ所有者のGitHubユーザー名です。
以後は毎月1日09:17 JST（00:17 UTC）のスケジュールで更新します。GitHub側の実行待ちによって開始時刻が遅れる場合があります。定期実行は既定ブランチに置いたワークフローから動作します。
## 専用ブランチ
生成画像・HTML・データは`contribution-graphs`ブランチへ保存します。既定ブランチにはコードと設定を置き、生成画像やデータはコミットしません。既定ブランチのREADMEも自動では書き換えません。
生成ブランチにはライト・ダークそれぞれの`profile-light.svg` / `profile-dark.svg`、`profile-light.png` / `profile-dark.png`、`profile-light.webp` / `profile-dark.webp`、`profile-light.html` / `profile-dark.html`、600pxフェード版の`profile-light3.svg` / `profile-dark3.svg`・PNG・WebP、画像内蔵の`dialog.html`と、従来URLの`contributions.svg`、`index.html`、`daily.csv`、`yearly.csv`、`monthly.csv`、`data.json`、`source.json`、`embed.md`、`README.md`、`.nojekyll`を出力します。
生成ブランチがなければ独立した履歴で作成し、以後は通常のコミットで更新します。force pushは使いません。同時実行はリポジトリ単位で直列化しています。
## READMEへの貼り付け
高さ600pxまでのフェード版は`profile-dark3.webp`と`profile-light3.webp`です。450pxから下を徐々に透明にし、元のマスや文字の位置は変えません。
同じブランチに画像を置く場合は次を使います。
```markdown
![profile](profile-dark3.webp#gh-dark-mode-only) \
![profile](profile-light3.webp#gh-light-mode-only)
```
画像は専用の`contribution-graphs`ブランチに生成します。別のREADMEから参照するときは、次のユーザー名・リポジトリ名を実際のものに置き換えます。初回実行後のActions Summaryと生成ブランチの`embed.md`には実行元に合わせたURLを出力します。
```markdown
![profile](https://raw.githubusercontent.com/YOUR_USER/YOUR_REPOSITORY/contribution-graphs/profile-dark3.webp#gh-dark-mode-only) \
![profile](https://raw.githubusercontent.com/YOUR_USER/YOUR_REPOSITORY/contribution-graphs/profile-light3.webp#gh-light-mode-only)
```
## ダイアログテンプレート
HTMLテンプレートは[templates/dialog.html](templates/dialog.html)です。600pxのフェード版をクリックすると、全体画像をスクロールできるダイアログで開きます。表示テーマに合わせて画像を切り替え、閉じるボタン・背景クリック・Escキーで閉じられます。
Actionsは`dialog.html`を生成ブランチへ出力します。4枚のWebPを内蔵した単独HTMLなので、ダウンロードしてブラウザーで開けます。GitHub Pagesを有効にした場合は`/dialog.html`でも表示できます。
READMEには上の画像記法を使用し、ダイアログはブラウザーまたはPagesで開きます。
## GitHub Pagesで公開する場合
リポジトリのSettings → Pages → Build and deployment → SourceをGitHub Actionsに設定してください。
続いてSettings → Secrets and variables → Actions → Variablesで`ENABLE_PAGES`を作り、値を`true`にします。Run workflowを実行すると、専用ブランチへの保存と同じ生成物をGitHub Pagesへデプロイします。公開URLはdeployジョブのEnvironmentリンクに表示されます。
Pagesを使わない場合は変数を作らず、そのままREADME用の画像更新だけを使えます。`ENABLE_PAGES`を無効にしても、既に公開したPagesサイトを自動削除する処理はありません。
生成ブランチからの通常のPagesビルドに依存せず、`upload-pages-artifact`と`deploy-pages`を使います。
## PNG・WebPの生成
ActionsでInkscapeを使って全体版は幅1600pxのPNG、フェード版は800×600pxのPNGを生成します。全体が600pxより短い場合は元の高さを保持します。その後ImageMagick 7で以下のコマンドを実行し、ロスレスWebPを生成します。PNGとWebPも同じ専用ブランチへ保存します。
```bash
magick mogrify -format webp -quality 100 -define webp:lossless=true -define webp:method=6 -define webp:exact=true profile-dark.png profile-light.png
magick mogrify -format webp -quality 100 -define webp:lossless=true -define webp:method=6 -define webp:exact=true profile-dark3.png profile-light3.png
```
変換後はImageMagickのcompareでPNGとWebPの画素差が0であることを確認し、一致した場合だけ公開します。READMEでは`#gh-dark-mode-only`と`#gh-light-mode-only`で表示テーマに応じてWebPを切り替えます。HTMLにはDark / Light切り替えボタンも付いています。
## 設定項目
Settings → Secrets and variables → Actions → Variablesで変更できます。
|変数|既定値|意味|
|---|---|---|
|`CONTRIBUTION_USER`|リポジトリ所有者|対象のGitHubユーザー名。Run workflowの`github_user`入力があればそちらを優先|
|`START_YEAR`|`2016`|取得する最初の年。2008年以降で指定|
|`CONTRIBUTION_SOURCE`|`auto`|`auto`はトークンがある場合に公式GraphQLを使用。`graphql`または`public`でも固定可能|
|`ENABLE_PAGES`|未設定|`true`の場合にGitHub Pagesへデプロイ|
ユーザー名は`github_user`入力 → `CONTRIBUTION_USER`変数 → リポジトリ所有者の順で決まります。組織所有のリポジトリで個人の草マップを作る場合は対象ユーザーを指定してください。
## APIの使い方と制限
Actionsでは自動発行される`GITHUB_TOKEN`を使い、公式GraphQL APIへ1年分ずつ直列でリクエストします。各リクエストの完了後に1.2秒以上あけてから次へ進みます。2016〜2026年なら11回です。各回に1年分の`contributionsCollection`とレート制限残量を含め、年別クエリの一括送信や並列実行は行いません。翌年も実行日の年まで自動で増えます。
個別のコミットやリポジトリを大量に巡回する処理はありません。レート制限情報はログと`data.json`へ記録し、HTTP 403/429やGraphQLエラーでは自動再試行・自動切り替えをせず終了します。
環境の権限でGraphQLを使えない場合は、`CONTRIBUTION_SOURCE=public`に設定できます。この場合も第三者のGitHub Contributions API v4を1年分ずつ直列取得し、通信完了後に1.2秒以上あけます。これに加えて、アカウント登録日を得る公式REST APIを最初に1回呼び出します。第三者APIは公開草マップを読み取る実装で、最長1時間のキャッシュがあり、未キャッシュの制限は10回/10秒/IPです。
`GITHUB_TOKEN`はワークフローで指定した`contents: write`権限を生成ブランチへのpushに使います。Pagesを使う場合だけ、別のdeployジョブに`pages: write`と`id-token: write`を付与しています。
## 日付と件数
実行日の判定はAsia/Tokyoです。終了日より後のマスは表示せず、統計と日別CSVから除外します。日付そのものはGitHubが返す値を保持し、日本時間への再配分はしません。
濃淡はGitHubの`contributionLevel`または公開草マップの`data-level`を0〜4へ対応付けて保持します。年ごとに異なる濃淡基準を統一し直すことはありません。ライト配色は`#eff2f5`、`#aceebb`、`#4ac26b`、`#2da44e`、`#116329`です。ダーク配色は添付のGitHub表示に合わせた`#151b23`、`#033a16`、`#196c2e`、`#2ea043`、`#56d364`で、背景は`#0d1117`です。
活動日は1件以上あった日です。登録前の日は0件として保持し、活動率と日平均の分母から除外します。全期間の連続記録は年をまたいで計算し、年別集計の最長連続はその年の中だけで計算します。年途中の前年比は前年の同じ月日までと比較します。
公開APIが登録前の年を省略する場合に限り、登録日より前の欠落日を0件として表示します。登録日以降のデータが欠けていれば生成を停止し、未知の日を0件で補完しません。
日別APIの件数・濃淡から計算するため、コミット・Issue・PR等の種類別内訳、各リポジトリ別内訳、活動本文は収録しません。非公開分は使用するAPIとトークンの閲覧可能範囲に従います。
## ローカル実行
Python 3.11以降とgitを使います。追加のPythonパッケージは不要です。PNG生成にはInkscape、WebP変換にはImageMagick 7を使います。Actionsでは自動で導入します。GraphQL用トークンは`GH_TOKEN`または`GITHUB_TOKEN`環境変数から読み込みます。
```bash
python3 scripts/generate.py --user DaisukeDaisuke --start-year 2016 --repository DaisukeDaisuke/github-contribution-map --output dist
```
トークンを使わずに公開草マップから取得する場合は`--source public`を追加してください。
```bash
python3 scripts/generate.py --user DaisukeDaisuke --source public --repository DaisukeDaisuke/github-contribution-map --output dist
```
`dist/index.html`をブラウザーで開くと、外部通信なしで日付選択、日別CSV・JSON保存が使えます。
既存の`data.json`から再生成する場合は、元データの終了日を指定します。この経路はAPIを呼び出しません。
```bash
python3 scripts/generate.py --input data.json --until 2026-10-28 --repository YOUR_USER/YOUR_REPOSITORY --output dist
python3 -m unittest discover -s tests -v
```
## ファイル構成
`.github/workflows/update-contributions.yml`が月次実行、生成ブランチへの保存、任意のPagesデプロイを行います。
`scripts/generate.py`がAPI取得と統計、`scripts/render_report.py`が縦長SVGとHTMLの描画、`scripts/render_images.py`が全体・フェード両テーマのPNG生成、`scripts/render_dialog.py`がダイアログHTML生成、`scripts/publish.py`が専用ブランチへの通常pushを担当します。
`tests/test_archive.py`は日付欠落、全年を結合した表の年末年始の連続性、年ごとの直列取得、通信完了後の待機、レート制限時の停止、統計、専用ブランチだけを更新する動作をネットワーク接続なしで確認します。
## 参照仕様
GitHub GraphQLユーザー・contributionCalendar：https://docs.github.com/en/graphql/reference/users
GitHub GraphQLのレート制限：https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api
GitHub Pagesカスタムワークフロー：https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
GitHubテンプレートリポジトリ：https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-template-repository
公開草マップAPIの実装と制限：https://github.com/grubersjoe/github-contributions-api
ImageMagick WebP仕様：https://imagemagick.org/webp/
ImageMagick導入アクション：https://github.com/mfinelli/setup-imagemagick
