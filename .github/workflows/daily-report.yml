name: Daily ERCOT Market Overview

on:
  schedule:
    # 07:15 CT — same cadence as hen-morning-report. CT is UTC-5 (CDT) or UTC-6 (CST);
    # this is set for CDT (summer). Adjust by 1 hour for CST months, or switch to two
    # cron entries if you want it to self-correct across the DST boundary.
    - cron: "15 12 * * *"
  workflow_dispatch: {}   # manual trigger for testing

jobs:
  discover-configs:
    runs-on: ubuntu-latest
    outputs:
      configs: ${{ steps.list.outputs.configs }}
    steps:
      - uses: actions/checkout@v4
      - id: list
        name: List customer configs (excluding template)
        run: |
          cd configs
          json=$(ls *.yaml | grep -v '^_template.yaml$' | jq -R -s -c 'split("\n")[:-1]')
          echo "configs=$json" >> "$GITHUB_OUTPUT"

  build-and-deploy:
    needs: discover-configs
    runs-on: ubuntu-latest
    strategy:
      matrix:
        config: ${{ fromJson(needs.discover-configs.outputs.configs) }}
      fail-fast: false   # one customer's build failing shouldn't block the others
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Build report for ${{ matrix.config }}
        env:
          ERCOT_API_USERNAME: ${{ secrets.ERCOT_API_USERNAME }}
          ERCOT_API_PASSWORD: ${{ secrets.ERCOT_API_PASSWORD }}
          ERCOT_SUBSCRIPTION_KEY: ${{ secrets.ERCOT_SUBSCRIPTION_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python pipeline/build_report.py --config "configs/${{ matrix.config }}"

      - name: Deploy to Cloudflare Pages
        uses: cloudflare/pages-action@v1
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          # projectName is read out of the config by build_report.py and written to
          # this file so the matrix doesn't need a second YAML parse step here.
          projectName: ${{ env.CF_PROJECT_NAME }}
          directory: dashboard
