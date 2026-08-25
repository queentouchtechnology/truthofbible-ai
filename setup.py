from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

from truth_of_bible import __version__ as version

setup(
    name="truth_of_bible",
    version=version,
    description=(
        "Truth of Bible — independent multilingual Bible intelligence AI "
        "backend for learn.truthofbible.org. Owns its own AI gateway "
        "(provider/model config, routing, retry/fallback), Bible "
        "explanation/Q&A generation, and LMS AI quiz generation. "
        "Deliberately has zero dependency on qtt_platform — this is not a "
        "QTT SaaS product."
    ),
    author="Queen Touch Technology",
    author_email="queentouchtech@gmail.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
