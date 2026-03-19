from setuptools import setup, find_packages

setup(
    name="urbanlst",
    version="2.0.0",
    packages=find_packages(include=["utils", "utils.*"]),
    py_modules=["urbanlst"],
    install_requires=[
        "earthengine-api",
        "geemap",
        "pandas",
        "numpy",
        "matplotlib",
        "seaborn",
        "rasterio",
        "plotly",
        "openpyxl",
    ],
    entry_points={
        "console_scripts": [
            "urbanlst = urbanlst:cli_main",
        ]
    },
    author="Jiyao Zhao",
    description=(
        "CLI tool for annual LCZ mapping and urban morphology analysis "
        "using Google Earth Engine, with three classification scenarios."
    ),
    license="MIT",
    python_requires=">=3.8",
)
