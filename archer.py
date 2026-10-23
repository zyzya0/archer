import time
import os

# code for archer


print(" --------------------------------------------------------  ")
print(" Welcome to Archer -- best tool for arch-based distros!")
print(" --------------------------------------------------------  ")

def actions():
    print("choose action:")
    print("1. install package")
    print("2. delete package")
    print("3. clean cache (not all)")
    print("4. update system")

actions()

choose = input ("? ")
if choose == "1":
    pkg = input("write name of package: ")
    os.system(f"sudo pacman -S {pkg} --noconfirm --needed")

if choose == "2":
    input(pkg)
    os.system(f"sudo pacman -Rns {pkg} --noconfirm")

if choose == "3":
    print("start cleaning")
    os.system("sudo pacman -Scc")

if choose == "4":
    os.system("sudo pacman -Syyu")

else choose:
    print("dont know this")
