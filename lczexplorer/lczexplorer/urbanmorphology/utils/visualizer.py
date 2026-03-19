# === visualizers/plotter.py ===
"""Visualization tools for analysis results"""
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt


class LSTPlotter:
    @staticmethod
    def plot_detrend_boxplot(city_id, df, change_class_mapping, class_order=None):
        """Create boxplot comparing day/night LST changes by urban morphology type"""

        # Merge with change class mapping
        df_plot = pd.merge(df, change_class_mapping, on='change')

        if class_order:
            df_plot = df_plot[df_plot['class'].isin(class_order)]
            df_plot['class'] = pd.Categorical(df_plot['class'], categories=class_order, ordered=True)

        # Reshape for plotting
        day_df = df_plot[['change', 'day_diff', 'class']].rename(columns={'day_diff': 'diff'})
        day_df['time'] = 'Day'

        night_df = df_plot[['change', 'night_diff', 'class']].rename(columns={'night_diff': 'diff'})
        night_df['time'] = 'Night'

        plot_df = pd.concat([day_df, night_df], ignore_index=True)

        # Create plot
        plt.figure(figsize=(12, 6))
        g = sns.boxplot(data=plot_df, x='class', y='diff', hue='time', palette='Set2')
        sns.stripplot(data=plot_df, x='class', y='diff', hue='time', dodge=True,
                      palette=['black', 'black'], size=3, jitter=0.2, alpha=0.4)

        plt.title(f'LST Change (Detrended) by Urban Change Type - City ID: {city_id}', fontsize=14)
        plt.xlabel('Urban Morphology Change Category', fontsize=12)
        plt.ylabel('LST Change (Δ°C)', fontsize=12)
        plt.xticks(rotation=45)
        plt.axhline(0, color='gray', linestyle='dashed', alpha=0.7)
        plt.tight_layout()

        # Clean legend
        handles, labels = g.get_legend_handles_labels()
        plt.legend(handles[:2], labels[:2], title='Time')

        return plt.gcf()


class LCZPlotter:
    @staticmethod
    def plot_lcz_changes(city_id, input_dir, output_dir, years, rule_csv):
        """Generate LCZ change visualizations using exported composites."""
        import os
        import numpy as np
        import rasterio
        import pandas as pd
        import matplotlib.pyplot as plt
        from collections import Counter
        import plotly.graph_objects as go

        os.makedirs(output_dir, exist_ok=True)

        lcz_stack_path = os.path.join(input_dir, f"LCZ_{city_id}_{years[0]}-{years[-1]}.tif")
        if not os.path.exists(lcz_stack_path):
            print(f"Missing LCZ stack for city {city_id}")
            return

        start = years[0]
        idx_2003 = years.index(2003) + 1 if 2003 in years else 1
        idx_2024 = years.index(2024) + 1 if 2024 in years else len(years)
        with rasterio.open(lcz_stack_path) as src:
            lcz_2003 = src.read(idx_2003)
            lcz_2024 = src.read(idx_2024)

        lcz_classes = list(range(1, 18))
        total_2003 = np.sum(np.isin(lcz_2003, lcz_classes))
        total_2024 = np.sum(np.isin(lcz_2024, lcz_classes))
        percent_2003 = [np.sum(lcz_2003 == c) / total_2003 * 100 for c in lcz_classes]
        percent_2024 = [np.sum(lcz_2024 == c) / total_2024 * 100 for c in lcz_classes]

        x = np.arange(len(lcz_classes))
        width = 0.35
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.bar(x - width / 2, percent_2003, width, label='Year 2003')
        ax.bar(x + width / 2, percent_2024, width, label='Year 2024')
        ax.set_xlabel('LCZ Class')
        ax.set_ylabel('Percentage (%)')
        ax.set_title('LCZ Class Distribution in 2003 vs 2024')
        ax.set_xticks(x)
        ax.set_xticklabels([str(c) for c in lcz_classes])
        ax.legend()
        plt.grid(True, axis='y', linestyle='--', alpha=0.6)
        plt.tight_layout()
        fig.savefig(os.path.join(output_dir, f"{city_id}_lcz_distribution.png"))
        plt.close(fig)

        # Yearly distributions
        yearly = []
        with rasterio.open(lcz_stack_path) as src:
            for year in years:
                idx = years.index(year) + 1
                try:
                    lcz_band = src.read(idx)
                except Exception:
                    yearly.append({'Year': year, **{c: 0 for c in lcz_classes}})
                    continue
                flat = lcz_band.flatten()
                flat = flat[(flat > 0) & (flat <= 17)]
                total = len(flat)
                counts = Counter(flat)
                yearly.append({'Year': year, **{c: counts.get(c, 0) / total * 100 if total else 0 for c in lcz_classes}})

        df = pd.DataFrame(yearly)
        df = df.melt(id_vars='Year', var_name='LCZ', value_name='Proportion')
        fig, axes = plt.subplots(nrows=6, ncols=3, figsize=(16, 20))
        axes = axes.flatten()
        for i, c in enumerate(lcz_classes):
            sub = df[df['LCZ'] == c]
            ax = axes[i]
            ax.plot(sub['Year'], sub['Proportion'], marker='o')
            ax.set_title(f"LCZ {c}")
            ax.set_xlabel('Year')
            ax.set_ylabel('Proportion (%)')
        for j in range(len(lcz_classes), len(axes)):
            fig.delaxes(axes[j])
        plt.tight_layout()
        fig.savefig(os.path.join(output_dir, f"{city_id}_lcz_trend.png"))
        plt.close(fig)

        # Sankey diagram
        valid = (lcz_2003 > 0) & (lcz_2003 <= 17) & (lcz_2024 > 0) & (lcz_2024 <= 17)
        lcz_2003v = lcz_2003[valid]
        lcz_2024v = lcz_2024[valid]
        matrix = np.zeros((17, 17), dtype=int)
        for i in range(1, 18):
            for j in range(1, 18):
                matrix[i-1, j-1] = np.sum((lcz_2003v == i) & (lcz_2024v == j))
        labels = [f"2003_{i}" for i in lcz_classes] + [f"2024_{i}" for i in lcz_classes]
        source, target, value = [], [], []
        for i in range(17):
            for j in range(17):
                if matrix[i, j] > 0:
                    source.append(i)
                    target.append(j + 17)
                    value.append(int(matrix[i, j]))
        fig = go.Figure(data=[go.Sankey(node=dict(label=labels, pad=15, thickness=20),
                                        link=dict(source=source, target=target, value=value))])
        fig.update_layout(title_text="LCZ Transitions: 2003 → 2024", font_size=12)
        fig.write_image(os.path.join(output_dir, f"{city_id}_lcz_transition_sankey.jpg"),
                        width=1000, height=600)

        # Change classification pie chart
        rules_df = pd.read_csv(rule_csv, dtype={'from': str, 'to': str, 'class': str})
        rules_dict = {(r['from'], r['to']): r['class'] for _, r in rules_df.iterrows()}
        pairs = list(zip(lcz_2003v.flatten(), lcz_2024v.flatten()))
        records = []
        for f, t in pairs:
            f_str, t_str = str(int(f)), str(int(t))
            category = 'stable' if f_str == t_str else rules_dict.get((f_str, t_str), 'unknown')
            records.append(category)
        df = pd.Series(records).value_counts().reset_index()
        df.columns = ['class', 'count']
        total = df['count'].sum()
        stable = df[df['class'] == 'stable']['count'].sum() if 'stable' in df['class'].values else 0
        non_stable_ratio = 1 - stable / total if total else 0
        plot_df = df[df['class'] != 'stable']
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.pie(plot_df['count'], labels=plot_df['class'], autopct='%1.1f%%', startangle=140)
        ax.set_title(f"LCZ Change Classification (2003–2024)\nNon-stable Area = {non_stable_ratio:.2%}")
        plt.tight_layout()
        fig.savefig(os.path.join(output_dir, f"{city_id}_lcz_change_pie.png"))
        plt.close(fig)
