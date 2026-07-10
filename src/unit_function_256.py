"""
===============================================================================
File      : unit_function_256.py
Purpose   : Define all basic function used for searching differential trails in SHA-2.

Dependencies:
    - SAT/SMT solver: STP
    - Python 3.x
===============================================================================
"""

from constrains import *

def generate_constraints(X, propagation_trail):
    fun = []
    for term in propagation_trail:
        temp = []
        for i in range(len(term)):
            if term[i] == '1':
                temp.append('(' + '~' + X[i] + ')')
            elif term[i] == '0':
                temp.append(X[i])
        fun.append('(' + "|".join(temp) + ')')
    constraint = 'ASSERT ' + '&'.join(fun) + ' = 0bin1' + ';\n'
    return constraint


def right_shift(order, num):
    return order[num:] + order[:num]


def left_shift(order, num):
    return order[-num:] + order[:-num]

def derive_cond(block_size, in_var_x, in_var_v_x, in_var_d_x):

    eqn = ""
    for i in range(block_size):
        temp = [in_var_x[i], in_var_v_x[i], in_var_d_x[i]]
        eqn += generate_constraints(temp, derive_cond_constrain)
    return eqn


def modadd_value(block_size, a, b, c, v):

    eqn = " ASSERT %s = 0bin0;\n" % c[0]
    for i in range(block_size, ):
        temp = [a[i], b[i], c[i], v[i], c[i + 1]]
        eqn += generate_constraints(temp, modular_addition_value_constrain)
    return eqn


# flag == 1: use the model 1 (expansion model for x → y)
# flag == 0: use the model 2 (expansion model for y = x)
def expand_model(block_size, in_var_v, in_var_d, c_var_v, c_var_d, out_var_v, out_var_d, flag):
    eqn = "ASSERT %s = 0bin0;\nASSERT %s = 0bin0;\n" % (c_var_v[0], c_var_d[0])
    if flag == 1:
        for i in range(block_size):
            temp = [in_var_v[i], in_var_d[i],
                    c_var_v[i], c_var_d[i],
                    out_var_v[i], out_var_d[i],
                    c_var_v[i + 1], c_var_d[i + 1]]
            eqn += generate_constraints(temp, expand_model_constrain_1)
    else:
        for i in range(block_size):
            temp = [out_var_v[i], out_var_d[i],
                    in_var_v[i], in_var_d[i],
                    c_var_v[i], c_var_d[i],
                    c_var_v[i + 1], c_var_d[i + 1]]
            eqn += generate_constraints(temp, expand_model_constrain_2)
    return eqn



# model z = x+y
def addition_function(block_size, in_var_v_0, in_var_d_0,
                      in_var_v_1, in_var_d_1,
                      in_var_c_v, in_var_c_d,
                      out_var_v, out_var_d):

    eqn = "ASSERT %s = 0bin0;\n" % (in_var_c_v[0])
    eqn += "ASSERT %s = 0bin0;\n" % (in_var_c_d[0])
    for i in range(block_size):
        temp = [in_var_v_0[i], in_var_d_0[i],
                in_var_v_1[i], in_var_d_1[i],
                in_var_c_v[i], in_var_c_d[i],
                out_var_v[i], out_var_d[i],
                in_var_c_v[i + 1], in_var_c_d[i + 1]]
        eqn += generate_constraints(temp, modular_addition_constrain)
    return eqn


# XOR model: full model (differential propagation + monitoring variables)
def xor_function(block_size, in_var_v_0, in_var_d_0, in_var_v_1, in_var_d_1, in_var_v_2, in_var_d_2, out_var_v,
                 out_var_d, in_var_0, in_var_1, in_var_2):
    
    eqn = ""
    for i in range(block_size):
        temp = [in_var_v_0[i], in_var_d_0[i],
                in_var_v_1[i], in_var_d_1[i],
                in_var_v_2[i], in_var_d_2[i],
                out_var_v[i], out_var_d[i],
                in_var_0[i], in_var_1[i], in_var_2[i]]
        eqn += generate_constraints(temp, xor_full_constrain)
    return eqn

# XOR model: full_model + conditions (differential propagation + monitoring variables + the number of bit conditions)
def xor_function_bitcondition(block_size, in_var_v_0, in_var_d_0, in_var_v_1, in_var_d_1, in_var_v_2, in_var_d_2, out_var_v,
                 out_var_d, in_var_0, in_var_1, in_var_2, in_var_d_n):
    
    eqn = ""
    for i in range(block_size):
        temp = [in_var_v_0[i], in_var_d_0[i],
                in_var_v_1[i], in_var_d_1[i],
                in_var_v_2[i], in_var_d_2[i],
                out_var_v[i], out_var_d[i],
                in_var_0[i], in_var_1[i], in_var_2[i],
                in_var_d_n[i]]
        eqn += generate_constraints(temp, xor_condition_constrain)
    return eqn


# MAJ model: full_model (differential propagation + monitoring variables)
def maj_function(block_size, in_var_v_0, in_var_d_0, in_var_v_1, in_var_d_1, in_var_v_2, in_var_d_2, out_var_v,
                 out_var_d, in_var_0, in_var_1, in_var_2):
    
    eqn = ""
    for i in range(block_size):
        temp = [in_var_v_0[i], in_var_d_0[i],
                in_var_v_1[i], in_var_d_1[i],
                in_var_v_2[i], in_var_d_2[i],
                out_var_v[i], out_var_d[i],
                in_var_0[i],
                in_var_1[i],
                in_var_2[i]]
        eqn += generate_constraints(temp, maj_full_constrain)
    return eqn

# 1: MAJ model: full model + conditions (differential propagation + monitoring variables + the number of bit conditions)
# 2: MAJ model: (x, y)-based modeling    
# 3: MAJ model:  x-based modeling
# 4: MAJ model: (y, z)-based modeling
# 5: MAJ model:  z-based modeling
def maj_function_bitcondition(block_size, in_var_v_0, in_var_d_0, in_var_v_1, in_var_d_1, in_var_v_2, in_var_d_2, out_var_v,
                 out_var_d, in_var_0, in_var_1, in_var_2, in_var_d_n, flag):

    eqn = ""
    if flag == 1:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_d_n[i]]
            eqn += generate_constraints(temp, maj_condition_constrain_1)
    elif flag == 2:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_d_n[i]]
            eqn += generate_constraints(temp, maj_condition_constrain_2)
    elif flag == 3:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_d_n[i]]
            eqn += generate_constraints(temp, maj_condition_constrain_3)
    elif flag == 4:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_d_n[i]]
            eqn += generate_constraints(temp, maj_condition_constrain_4)
    elif flag == 5:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_d_n[i]]
            eqn += generate_constraints(temp, maj_condition_constrain_5)

    return eqn


# IF model: full model (differential propagation + monitoring variables)      
def if_function(block_size, in_var_v_0, in_var_d_0, in_var_v_1, in_var_d_1, in_var_v_2, in_var_d_2, out_var_v,
                out_var_d, in_var_0, in_var_1, in_var_2):

    eqn = ""
    for i in range(block_size):
        temp = [in_var_v_1[i], in_var_d_1[i],
                in_var_v_2[i], in_var_d_2[i],
                in_var_v_0[i], in_var_d_0[i],
                out_var_v[i], out_var_d[i],
                in_var_1[i],
                in_var_2[i],
                in_var_0[i]]
        eqn += generate_constraints(temp, ifz_full_constrain)
    return eqn


# 1: IF model: full model + conditions (differential propagation + monitoring variables + the number of bit conditions)
# 4: IF model: (y, z)-based modeling
def if_function_bitcondition_1_4(block_size, in_var_v_0, in_var_d_0, in_var_v_1, in_var_d_1, in_var_v_2, in_var_d_2, out_var_v,
                out_var_d, in_var_0, in_var_1, in_var_2, in_var_v_n, in_var_d_n, flag):

    eqn = ""
    if flag == 1:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_v_n[i], in_var_d_n[i]]
            eqn += generate_constraints(temp, ifx_condition_constrain_1)
    elif flag == 4:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_v_n[i], in_var_d_n[i]]
            eqn += generate_constraints(temp, ifx_condition_constrain_4)

    return eqn


# 2: IF model: (x, y)-based modeling
# 3: IF model: x-based modeling
# 5: IF model: z-based modeling
def if_function_bitcondition_2_3_5(block_size, in_var_v_0, in_var_d_0, in_var_v_1, in_var_d_1, in_var_v_2, in_var_d_2, out_var_v,
                out_var_d, in_var_0, in_var_1, in_var_2, in_var_d_n, flag):
    
    eqn = ""
    if flag == 2:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_d_n[i]]
            eqn += generate_constraints(temp, ifx_condition_constrain_2)
    elif flag == 3:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_d_n[i]]
            eqn += generate_constraints(temp, ifx_condition_constrain_3)
    elif flag == 5:
        for i in range(block_size):
            temp = [in_var_v_0[i], in_var_d_0[i],
                    in_var_v_1[i], in_var_d_1[i],
                    in_var_v_2[i], in_var_d_2[i],
                    out_var_v[i], out_var_d[i],
                    in_var_0[i],
                    in_var_1[i],
                    in_var_2[i],
                    in_var_d_n[i]]
            eqn += generate_constraints(temp, ifx_condition_constrain_5)

    return eqn


def boolean_value(block_size, x0, x1, x2, out, fna):
    eqn = ""
    if fna == "MAJ":
        for i in range(block_size):
            temp = [x0[i], x1[i], x2[i], out[i]]
            eqn += generate_constraints(temp, maj_value_constrain)
    elif fna == "XOR":
        for i in range(block_size):
            temp = [x0[i], x1[i], x2[i], out[i]]
            eqn += generate_constraints(temp, xor_value_constrain)
    elif fna == "IF":
        for i in range(block_size):
            temp = [x0[i], x1[i], x2[i], out[i]]
            eqn += generate_constraints(temp, ifx_value_constrain)
    return eqn


def sha_e(block_size, __op0, __op1, __op2, step):
    # Store all generated constraints
    eqn__constraints = []
    # Store all declared variables
    eqn__variable = []
    in_var_v_m = []
    in_var_d_m = []
    # message words
    for j in range(block_size):
        in_var_v_m.append("wv" + "_" + str(step) + "_" + str(j))
        in_var_d_m.append("wd" + "_" + str(step) + "_" + str(j))
        eqn__variable.append("wv" + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
        eqn__variable.append("wd" + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
    in_var_v_a0 = []
    in_var_d_a0 = []
    in_var_v_e = []
    in_var_d_e = []
    in_var_e = []
    # A_i-4
    for j in range(block_size):
        in_var_v_a0.append("xv" + "_" + str(step - 4) + "_" + str(j))
        in_var_d_a0.append("xd" + "_" + str(step - 4) + "_" + str(j))
        eqn__variable.append("xv" + "_" + str(step - 4) + "_" + str(j) + ": BITVECTOR(1);\n")
        eqn__variable.append("xd" + "_" + str(step - 4) + "_" + str(j) + ": BITVECTOR(1);\n")
    # E
    for i in range(5):
        temp_b_v = []
        temp_b_d = []
        for j in range(block_size):
            temp_b_v.append("yv" + "_" + str(step - 4 + i) + "_" + str(j))
            temp_b_d.append("yd" + "_" + str(step - 4 + i) + "_" + str(j))
            eqn__variable.append("yv" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("yd" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_e.append(temp_b_v)
        in_var_d_e.append(temp_b_d)

    # the value of E
    for i in range(4):
        temp_b = []
        for j in range(block_size):
            temp_b.append("y" + "_" + str(step - 4 + i) + "_" + str(j))
        if i > 0:
            for j in range(block_size):
                eqn__variable.append("y" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_e.append(temp_b)

    # some intermediate variables
    in_var_v_b = []
    in_var_d_b = []
    for i in range(0, 6):
        temp_b_v = []
        temp_b_d = []
        for j in range(block_size):
            temp_b_v.append("bv" + str(i) + "_" + str(step) + "_" + str(j))
            temp_b_d.append("bd" + str(i) + "_" + str(step) + "_" + str(j))
            eqn__variable.append("bv" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("bd" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_b.append(temp_b_v)
        in_var_d_b.append(temp_b_d)

    # some carry variables
    in_var_v_c = []
    in_var_d_c = []
    for i in range(5):
        temp_c_v = []
        temp_c_d = []
        for j in range(block_size + 1):
            temp_c_v.append("cv" + str(i) + "_" + str(step) + "_" + str(j))
            temp_c_d.append("cd" + str(i) + "_" + str(step) + "_" + str(j))
            eqn__variable.append("cv" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("cd" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_c.append(temp_c_v)
        in_var_d_c.append(temp_c_d)


    # Variable representing the number of bit conditions derived by Boolean function Sigma1
    if __op0 == 1:
        in_var_d_ne_xor = []
        for j in range(block_size):
            in_var_d_ne_xor.append("ned_xor_" + str(step) + "_" + str(j))
            eqn__variable.append("ned_xor_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")

        eqn__constraints.append(xor_function_bitcondition(block_size,
                                             right_shift(in_var_v_e[3], 6), right_shift(in_var_d_e[3], 6),
                                             right_shift(in_var_v_e[3], 11), right_shift(in_var_d_e[3], 11),
                                             right_shift(in_var_v_e[3], 25), right_shift(in_var_d_e[3], 25),
                                             in_var_v_b[0], in_var_d_b[0],
                                             right_shift(in_var_e[3], 6),
                                             right_shift(in_var_e[3], 11),
                                             right_shift(in_var_e[3], 25),
                                             in_var_d_ne_xor))
    else:
        eqn__constraints.append(xor_function(block_size,
                                            right_shift(in_var_v_e[3], 6), right_shift(in_var_d_e[3], 6),
                                            right_shift(in_var_v_e[3], 11), right_shift(in_var_d_e[3], 11),
                                            right_shift(in_var_v_e[3], 25), right_shift(in_var_d_e[3], 25),
                                            in_var_v_b[0], in_var_d_b[0],
                                            right_shift(in_var_e[3], 6),
                                            right_shift(in_var_e[3], 11),
                                            right_shift(in_var_e[3], 25)))
    
    # Variable representing the number of bit conditions derived by Boolean function IF
    if __op1 == 1 or __op1 == 4:
        in_var_v_ne_ifz = []
        in_var_d_ne_ifz = []
        for j in range(block_size):
            in_var_v_ne_ifz.append("nev_if_" + str(step) + "_" + str(j))
            in_var_d_ne_ifz.append("ned_if_" + str(step) + "_" + str(j))
            eqn__variable.append("nev_if_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("ned_if_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")

        eqn__constraints.append(if_function_bitcondition_1_4(block_size,
                                            in_var_v_e[3], in_var_d_e[3],
                                            in_var_v_e[2], in_var_d_e[2],
                                            in_var_v_e[1], in_var_d_e[1],
                                            in_var_v_b[1], in_var_d_b[1],
                                            in_var_e[3],
                                            in_var_e[2],
                                            in_var_e[1],
                                            in_var_v_ne_ifz, 
                                            in_var_d_ne_ifz,
                                            __op1))
    
    elif __op1 == 2 or __op1 == 3 or __op1 == 5:
        in_var_d_ne_ifz = []
        for j in range(block_size):
            in_var_d_ne_ifz.append("ned_if_" + str(step) + "_" + str(j))
            eqn__variable.append("ned_if_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")

        eqn__constraints.append(if_function_bitcondition_2_3_5(block_size,
                                            in_var_v_e[3], in_var_d_e[3],
                                            in_var_v_e[2], in_var_d_e[2],
                                            in_var_v_e[1], in_var_d_e[1],
                                            in_var_v_b[1], in_var_d_b[1],
                                            in_var_e[3],
                                            in_var_e[2],
                                            in_var_e[1],
                                            in_var_d_ne_ifz,
                                            __op1))
    else:
        eqn__constraints.append(if_function(block_size,
                                            in_var_v_e[3], in_var_d_e[3],
                                            in_var_v_e[2], in_var_d_e[2],
                                            in_var_v_e[1], in_var_d_e[1],
                                            in_var_v_b[1], in_var_d_b[1],
                                            in_var_e[3],
                                            in_var_e[2],
                                            in_var_e[1]))

    eqn__constraints.append(addition_function(block_size,
                                              in_var_v_e[0], in_var_d_e[0],
                                              in_var_v_b[0], in_var_d_b[0],
                                              in_var_v_c[0], in_var_d_c[0],
                                              in_var_v_b[2], in_var_d_b[2]))
    eqn__constraints.append(addition_function(block_size,
                                              in_var_v_b[2], in_var_d_b[2],
                                              in_var_v_b[1], in_var_d_b[1],
                                              in_var_v_c[1], in_var_d_c[1],
                                              in_var_v_b[3], in_var_d_b[3]))
    eqn__constraints.append(addition_function(block_size,
                                              in_var_v_m, in_var_d_m,
                                              in_var_v_b[3], in_var_d_b[3],
                                              in_var_v_c[2], in_var_d_c[2],
                                              in_var_v_b[5], in_var_d_b[5]))
    # computer Ei
    eqn__constraints.append(addition_function(block_size,
                                              in_var_v_a0, in_var_d_a0,
                                              in_var_v_b[5], in_var_d_b[5],
                                              in_var_v_c[3], in_var_d_c[3],
                                              in_var_v_b[4], in_var_d_b[4]))
    
    eqn__constraints.append(expand_model(block_size,
                                            in_var_v_b[4], in_var_d_b[4],
                                            in_var_v_c[4], in_var_d_c[4],
                                            in_var_v_e[4], in_var_d_e[4], __op2))
    
    return eqn__variable, eqn__constraints


def sha_a(block_size, __op3, __op4, __op5, step):
    eqn__variable = []
    eqn__constraints = []

    # A
    in_var_v_a = []
    in_var_d_a = []
    in_var_a = []
    for i in range(5):
        temp_b_v = []
        temp_b_d = []
        for j in range(block_size):
            temp_b_v.append("xv" + "_" + str(step - 4 + i) + "_" + str(j))
            temp_b_d.append("xd" + "_" + str(step - 4 + i) + "_" + str(j))
        if i > 0:
            for j in range(block_size):
                eqn__variable.append("xv" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
                eqn__variable.append("xd" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_a.append(temp_b_v)
        in_var_d_a.append(temp_b_d)

    # the value of A
    for i in range(4):
        temp_b = []
        for j in range(block_size):
            temp_b.append("x" + "_" + str(step - 4 + i) + "_" + str(j))
        if i > 0:
            for j in range(block_size):
                eqn__variable.append("x" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_a.append(temp_b)

    # some intermediate variables
    in_var_v_b = []
    in_var_d_b = []
    for i in range(10):
        temp_b_v = []
        temp_b_d = []
        for j in range(block_size):
            temp_b_v.append("bv" + str(i) + "_" + str(step) + "_" + str(j))
            temp_b_d.append("bd" + str(i) + "_" + str(step) + "_" + str(j))
        if i > 4:
            for j in range(block_size):
                eqn__variable.append("bv" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
                eqn__variable.append("bd" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_b.append(temp_b_v)
        in_var_d_b.append(temp_b_d)

    # some carry variables
    in_var_v_c = []
    in_var_d_c = []
    for i in range(8):
        temp_c_v = []
        temp_c_d = []
        for j in range(block_size + 1):
            temp_c_v.append("cv" + str(i) + "_" + str(step) + "_" + str(j))
            temp_c_d.append("cd" + str(i) + "_" + str(step) + "_" + str(j))
        if i > 4:
            for j in range(block_size + 1):
                eqn__variable.append("cv" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
                eqn__variable.append("cd" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_c.append(temp_c_v)
        in_var_d_c.append(temp_c_d)

    # Variable representing the number of bit conditions derived by Boolean function Sigma0
    if __op3 == 1:
        in_var_d_na_xor = []
        for j in range(block_size):
            in_var_d_na_xor.append("nad_xor_" + str(step) + "_" + str(j))
            eqn__variable.append("nad_xor_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")

        eqn__constraints.append(xor_function_bitcondition(block_size,
                                             right_shift(in_var_v_a[3], 2), right_shift(in_var_d_a[3], 2),
                                             right_shift(in_var_v_a[3], 13), right_shift(in_var_d_a[3], 13),
                                             right_shift(in_var_v_a[3], 22), right_shift(in_var_d_a[3], 22),
                                             in_var_v_b[6], in_var_d_b[6],
                                             right_shift(in_var_a[3], 2),
                                             right_shift(in_var_a[3], 13),
                                             right_shift(in_var_a[3], 22),
                                             in_var_d_na_xor))
    else: 
        eqn__constraints.append(xor_function(block_size,
                                             right_shift(in_var_v_a[3], 2), right_shift(in_var_d_a[3], 2),
                                             right_shift(in_var_v_a[3], 13), right_shift(in_var_d_a[3], 13),
                                             right_shift(in_var_v_a[3], 22), right_shift(in_var_d_a[3], 22),
                                             in_var_v_b[6], in_var_d_b[6],
                                             right_shift(in_var_a[3], 2),
                                             right_shift(in_var_a[3], 13),
                                             right_shift(in_var_a[3], 22)))

    # Variable representing the number of bit conditions derived by Boolean function MAJ
    if __op4 != 0:
        in_var_d_na_maj = []
        for j in range(block_size):
            in_var_d_na_maj.append("nad_maj_" + str(step) + "_" + str(j))
            eqn__variable.append("nad_maj_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
        
        eqn__constraints.append(maj_function_bitcondition(block_size, in_var_v_a[3], in_var_d_a[3],
                                                    in_var_v_a[2], in_var_d_a[2],
                                                    in_var_v_a[1], in_var_d_a[1],
                                                    in_var_v_b[7], in_var_d_b[7],
                                                    in_var_a[3],
                                                    in_var_a[2],
                                                    in_var_a[1],
                                                    in_var_d_na_maj,
                                                    __op4))
        
    else:
        eqn__constraints.append(maj_function(block_size, in_var_v_a[3], in_var_d_a[3],
                                             in_var_v_a[2], in_var_d_a[2],
                                             in_var_v_a[1], in_var_d_a[1],
                                             in_var_v_b[7], in_var_d_b[7],
                                             in_var_a[3],
                                             in_var_a[2],
                                             in_var_a[1]))


    eqn__constraints.append(addition_function(block_size,
                                              in_var_v_b[5], in_var_d_b[5],
                                              in_var_v_b[6], in_var_d_b[6],
                                              in_var_v_c[5], in_var_d_c[5],
                                              in_var_v_b[8], in_var_d_b[8]))

    eqn__constraints.append(addition_function(block_size,
                                              in_var_v_b[8], in_var_d_b[8],
                                              in_var_v_b[7], in_var_d_b[7],
                                              in_var_v_c[6], in_var_d_c[6],
                                              in_var_v_b[9], in_var_d_b[9]))

    eqn__constraints.append(expand_model(block_size,
                                            in_var_v_b[9], in_var_d_b[9],
                                            in_var_v_c[7], in_var_d_c[7],
                                            in_var_v_a[4], in_var_d_a[4], __op5))
    return eqn__variable, eqn__constraints


def message_expand(block_size, __op6, __op7, __op8, step):
    eqn__constraints = []
    eqn__variable = []
    in_var_v_w = []
    in_var_d_w = []
    
    in_var_w0 = []
    in_var_w2 = []
    index = [2, 7, 15, 16, 0]
    # W
    for i in range(len(index)):
        temp_b_v = []
        temp_b_d = []
        for j in range(block_size):
            temp_b_v.append("wv" + "_" + str(step - index[i]) + "_" + str(j))
            temp_b_d.append("wd" + "_" + str(step - index[i]) + "_" + str(j))
            eqn__variable.append("wv" + "_" + str(step - index[i]) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("wd" + "_" + str(step - index[i]) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_w.append(temp_b_v)
        in_var_d_w.append(temp_b_d)

    # the value of W
    for j in range(block_size):
        in_var_w0.append("w" + "_" + str(step - 2) + "_" + str(j))
        eqn__variable.append("w" + "_" + str(step - 2) + "_" + str(j) + ": BITVECTOR(1);\n")
    for j in range(block_size):
        in_var_w2.append("w" + "_" + str(step - 15) + "_" + str(j))
        eqn__variable.append("w" + "_" + str(step - 15) + "_" + str(j) + ": BITVECTOR(1);\n")

    # some intermediate variables
    in_var_v_b = []
    in_var_d_b = []
    for i in range(5):
        temp_b_v = []
        temp_b_d = []
        for j in range(block_size):
            temp_b_v.append("mbv" + str(i) + "_" + str(step) + "_" + str(j))
            temp_b_d.append("mbd" + str(i) + "_" + str(step) + "_" + str(j))
            eqn__variable.append("mbv" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("mbd" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_b.append(temp_b_v)
        in_var_d_b.append(temp_b_d)
    
    # some carry variables
    in_var_v_c = []
    in_var_d_c = []
    for i in range(4):
        temp_c_v = []
        temp_c_d = []
        for j in range(block_size + 1):
            temp_c_v.append("mcv" + str(i) + "_" + str(step) + "_" + str(j))
            temp_c_d.append("mcd" + str(i) + "_" + str(step) + "_" + str(j))
            eqn__variable.append("mcv" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("mcd" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_c.append(temp_c_v)
        in_var_d_c.append(temp_c_d)

    temp_v0 = []
    temp_d0 = []
    temp_v1 = []
    temp_d1 = []
    temp_0 = []
    temp_1 = []
    for i in range(10):
        temp_v0.append("temp0v" + "_" + str(step) + "_" + str(i))
        temp_d0.append("temp0d" + "_" + str(step) + "_" + str(i))
        temp_0.append("temp0" + "_" + str(step) + "_" + str(i))
        eqn__variable.append("temp0v" + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        eqn__variable.append("temp0d" + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        eqn__variable.append("temp0" + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
    for i in range(3):
        temp_v1.append("temp1v" + "_" + str(step) + "_" + str(i))
        temp_d1.append("temp1d" + "_" + str(step) + "_" + str(i))
        temp_1.append("temp1" + "_" + str(step) + "_" + str(i))
        eqn__variable.append("temp1v" + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        eqn__variable.append("temp1d" + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        eqn__variable.append("temp1" + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
    for i in range(10):
        temp = "ASSERT %s = 0bin0;\n" % temp_v0[i]
        temp += "ASSERT %s = 0bin0;\n" % temp_d0[i]
        temp += "ASSERT %s = 0bin0;\n" % temp_0[i]
        eqn__constraints.append(temp)
    for i in range(3):
        temp = "ASSERT %s = 0bin0;\n" % temp_v1[i]
        temp += "ASSERT %s = 0bin0;\n" % temp_d1[i]
        temp += "ASSERT %s = 0bin0;\n" % temp_1[i]
        eqn__constraints.append(temp)


    # Variable representing the number of bit conditions derived by Boolean function sigma1 and sigma0
    if __op6 == 1 and __op7 == 1:
        in_var_d_nm_xor = []
        for i in range(2):
            temp_n_md = []
            for j in range(block_size):
                temp_n_md.append("nmd_xor" + str(i) + "_" + str(step) + "_" + str(j))
                eqn__variable.append("nmd_xor" + str(i) + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
            in_var_d_nm_xor.append(temp_n_md)

        eqn__constraints.append(xor_function_bitcondition(block_size,
                                             right_shift(in_var_v_w[0], 17), right_shift(in_var_d_w[0], 17),
                                             right_shift(in_var_v_w[0], 19), right_shift(in_var_d_w[0], 19),
                                             right_shift(in_var_v_w[0], 10)[:22] + temp_v0,
                                             right_shift(in_var_d_w[0], 10)[:22] + temp_d0,
                                             in_var_v_b[0], in_var_d_b[0],
                                             right_shift(in_var_w0, 17),
                                             right_shift(in_var_w0, 19),
                                             right_shift(in_var_w0, 10)[:22] + temp_0,
                                             in_var_d_nm_xor[0]))
        
        eqn__constraints.append(xor_function_bitcondition(block_size,
                                             right_shift(in_var_v_w[2], 7), right_shift(in_var_d_w[2], 7),
                                             right_shift(in_var_v_w[2], 18), right_shift(in_var_d_w[2], 18),
                                             right_shift(in_var_v_w[2], 3)[:29] + temp_v1,
                                             right_shift(in_var_d_w[2], 3)[:29] + temp_d1,
                                             in_var_v_b[2], in_var_d_b[2],
                                             right_shift(in_var_w2, 7),
                                             right_shift(in_var_w2, 18),
                                             right_shift(in_var_w2, 3)[:29] + temp_1,
                                             in_var_d_nm_xor[1]))
    else:
        eqn__constraints.append(xor_function(block_size,
                                                right_shift(in_var_v_w[0], 17), right_shift(in_var_d_w[0], 17),
                                                right_shift(in_var_v_w[0], 19), right_shift(in_var_d_w[0], 19),
                                                right_shift(in_var_v_w[0], 10)[:22] + temp_v0,
                                                right_shift(in_var_d_w[0], 10)[:22] + temp_d0,
                                                in_var_v_b[0], in_var_d_b[0],
                                                right_shift(in_var_w0, 17),
                                                right_shift(in_var_w0, 19),
                                                right_shift(in_var_w0, 10)[:22] + temp_0))
        
        eqn__constraints.append(xor_function(block_size,
                                                right_shift(in_var_v_w[2], 7), right_shift(in_var_d_w[2], 7),
                                                right_shift(in_var_v_w[2], 18), right_shift(in_var_d_w[2], 18),
                                                right_shift(in_var_v_w[2], 3)[:29] + temp_v1,
                                                right_shift(in_var_d_w[2], 3)[:29] + temp_d1,
                                                in_var_v_b[2], in_var_d_b[2],
                                                right_shift(in_var_w2, 7),
                                                right_shift(in_var_w2, 18),
                                                right_shift(in_var_w2, 3)[:29] + temp_1))

    eqn__constraints.append(addition_function(block_size,
                                              in_var_v_b[0], in_var_d_b[0],
                                              in_var_v_w[1], in_var_d_w[1],
                                              in_var_v_c[0], in_var_d_c[0],
                                              in_var_v_b[1], in_var_d_b[1]))
    
    eqn__constraints.append(addition_function(block_size,
                                              in_var_v_b[1], in_var_d_b[1],
                                              in_var_v_b[2], in_var_d_b[2],
                                              in_var_v_c[1], in_var_d_c[1],
                                              in_var_v_b[3], in_var_d_b[3]))
    eqn__constraints.append(addition_function(block_size, in_var_v_b[3], in_var_d_b[3],
                                              in_var_v_w[3], in_var_d_w[3],
                                              in_var_v_c[2], in_var_d_c[2],
                                              in_var_v_b[4], in_var_d_b[4]))
    
    eqn__constraints.append(expand_model(block_size,
                                            in_var_v_b[4], in_var_d_b[4],
                                            in_var_v_c[3], in_var_d_c[3],
                                            in_var_v_w[4], in_var_d_w[4], __op8))

    return eqn__variable, eqn__constraints


def sha2_value(block_size, fna0, fna1, step):
    eqn__constraints = []
    eqn__variable = []
    in_var_v_m = []
    in_var_d_m = []
    m = []
    c = []

    for i in range(block_size):
        in_var_v_m.append("wv_" + str(step) + "_" + str(i))
        eqn__variable.append("wv_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        in_var_d_m.append("wd_" + str(step) + "_" + str(i))
        eqn__variable.append("wd_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
    for i in range(block_size):
        m.append("w_" + str(step) + "_" + str(i))
        eqn__variable.append("w_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")

    for i in range(block_size):
        c.append("constant_" + str(step) + "_" + str(i))
        eqn__constraints.append("ASSERT constant_" + str(step) + "_" + str(block_size - i - 1) + " = 0bin%s;\n" % (
            bin(k_constant_256[step])[2:].zfill(32)[i]))
        eqn__variable.append("constant_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
    
    in_var_v_e = []
    in_var_d_e = []
    in_var_v_a = []
    in_var_d_a = []
    e = []
    a = []
    for i in range(5):
        temp_b_v = []
        temp_b_d = []
        for j in range(block_size):
            temp_b_v.append("yv" + "_" + str(step - 4 + i) + "_" + str(j))
            temp_b_d.append("yd" + "_" + str(step - 4 + i) + "_" + str(j))
            eqn__variable.append("yv" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("yd" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_e.append(temp_b_v)
        in_var_d_e.append(temp_b_d)

    for i in range(5):
        temp_b_v = []
        for j in range(block_size):
            temp_b_v.append("y" + "_" + str(step - 4 + i) + "_" + str(j))
            eqn__variable.append("y" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
        e.append(temp_b_v)
    for i in range(5):
        temp_b_v = []
        for j in range(block_size):
            temp_b_v.append("x" + "_" + str(step - 4 + i) + "_" + str(j))
            eqn__variable.append("x" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
        a.append(temp_b_v)

    for i in range(5):
        temp_b_v = []
        temp_b_d = []
        for j in range(block_size):
            temp_b_v.append("xv" + "_" + str(step - 4 + i) + "_" + str(j))
            temp_b_d.append("xd" + "_" + str(step - 4 + i) + "_" + str(j))
            eqn__variable.append("xv" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
            eqn__variable.append("xd" + "_" + str(step - 4 + i) + "_" + str(j) + ": BITVECTOR(1);\n")
        in_var_v_a.append(temp_b_v)
        in_var_d_a.append(temp_b_d)

    eqn__constraints.append(derive_cond(block_size, m, in_var_v_m, in_var_d_m))
    eqn__constraints.append(derive_cond(block_size, a[0], in_var_v_a[0], in_var_d_a[0]))
    eqn__constraints.append(derive_cond(block_size, a[1], in_var_v_a[1], in_var_d_a[1]))
    eqn__constraints.append(derive_cond(block_size, a[2], in_var_v_a[2], in_var_d_a[2]))
    eqn__constraints.append(derive_cond(block_size, a[3], in_var_v_a[3], in_var_d_a[3]))
    eqn__constraints.append(derive_cond(block_size, a[4], in_var_v_a[4], in_var_d_a[4]))

    eqn__constraints.append(derive_cond(block_size, e[0], in_var_v_e[0], in_var_d_e[0]))
    eqn__constraints.append(derive_cond(block_size, e[1], in_var_v_e[1], in_var_d_e[1]))
    eqn__constraints.append(derive_cond(block_size, e[2], in_var_v_e[2], in_var_d_e[2]))
    eqn__constraints.append(derive_cond(block_size, e[3], in_var_v_e[3], in_var_d_e[3]))
    eqn__constraints.append(derive_cond(block_size, e[4], in_var_v_e[4], in_var_d_e[4]))

    in_var_b = []
    for j in range(9):
        in_var_bc = []
        for i in range(block_size):
            in_var_bc.append("b" + str(j) + "_" + str(step) + "_" + str(i))
            eqn__variable.append("b" + str(j) + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        in_var_b.append(in_var_bc)

    in_var_c = []
    for j in range(7):
        in_var_cm = []
        for i in range(block_size + 1):
            in_var_cm.append("c" + str(j) + "_" + str(step) + "_" + str(i))
            eqn__variable.append("c" + str(j) + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        in_var_c.append(in_var_cm)

    eqn__constraints.append(
        boolean_value(block_size, right_shift(e[3], 6), right_shift(e[3], 11), right_shift(e[3], 25),
                      in_var_b[0], "XOR"))
    eqn__constraints.append(boolean_value(block_size, e[3], e[2], e[1], in_var_b[1], fna0))
    eqn__constraints.append(modadd_value(block_size, in_var_b[0], in_var_b[1], in_var_c[0], in_var_b[2]))
    eqn__constraints.append(modadd_value(block_size, m, in_var_b[2], in_var_c[1], in_var_b[3]))
    eqn__constraints.append(modadd_value(block_size, c, in_var_b[3], in_var_c[2], in_var_b[4]))
    eqn__constraints.append(modadd_value(block_size, e[0], in_var_b[4], in_var_c[3], in_var_b[5]))
    # computer ei
    eqn__constraints.append(modadd_value(block_size, a[0], in_var_b[5], in_var_c[4], e[4]))
    # computer ai
    eqn__constraints.append(
        boolean_value(block_size, right_shift(a[3], 2), right_shift(a[3], 13), right_shift(a[3], 22),
                      in_var_b[6], "XOR"))
    eqn__constraints.append(boolean_value(block_size, a[3], a[2], a[1], in_var_b[7], fna1))
    eqn__constraints.append(modadd_value(block_size, in_var_b[5], in_var_b[6], in_var_c[5], in_var_b[8]))
    eqn__constraints.append(modadd_value(block_size, in_var_b[7], in_var_b[8], in_var_c[6], a[4]))
    return eqn__variable, eqn__constraints


def message_expand_value(block_size, step):
    eqn__constraints = []
    eqn__variable = []
    
    in_var_w0 = []
    in_var_w1 = []
    in_var_w2 = []
    in_var_w3 = []
    in_var_w4 = []
    
    for j in range(block_size):
        in_var_w0.append("w" + "_" + str(step - 2) + "_" + str(j))
        eqn__variable.append("w" + "_" + str(step - 2) + "_" + str(j) + ": BITVECTOR(1);\n")
    for j in range(block_size):
        in_var_w1.append("w" + "_" + str(step - 7) + "_" + str(j))
        eqn__variable.append("w" + "_" + str(step - 7) + "_" + str(j) + ": BITVECTOR(1);\n")
    for j in range(block_size):
        in_var_w2.append("w" + "_" + str(step - 15) + "_" + str(j))
        eqn__variable.append("w" + "_" + str(step - 15) + "_" + str(j) + ": BITVECTOR(1);\n")
    for j in range(block_size):
        in_var_w3.append("w" + "_" + str(step - 16) + "_" + str(j))
        eqn__variable.append("w" + "_" + str(step - 16) + "_" + str(j) + ": BITVECTOR(1);\n")
    for j in range(block_size):
        in_var_w4.append("w" + "_" + str(step) + "_" + str(j))
        eqn__variable.append("w" + "_" + str(step) + "_" + str(j) + ": BITVECTOR(1);\n")
    

    in_var_b = []
    for j in range(9, 13):
        in_var_bc = []
        for i in range(block_size):
            in_var_bc.append("b" + str(j) + "_" + str(step) + "_" + str(i))
            eqn__variable.append("b" + str(j) + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        in_var_b.append(in_var_bc)

    in_var_c = []
    for j in range(7, 10):
        in_var_cm = []
        for i in range(block_size + 1):
            in_var_cm.append("c" + str(j) + "_" + str(step) + "_" + str(i))
            eqn__variable.append("c" + str(j) + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
        in_var_c.append(in_var_cm)

    temp_0 = []
    temp_1 = []
    for i in range(10):
        temp_0.append("temp0" + "_" + str(step) + "_" + str(i))
        eqn__variable.append("temp0" + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
    for i in range(3):
        temp_1.append("temp1" + "_" + str(step) + "_" + str(i))
        eqn__variable.append("temp1" + "_" + str(step) + "_" + str(i) + ": BITVECTOR(1);\n")
    for i in range(10):
        temp = "ASSERT %s = 0bin0;\n" % temp_0[i]
        eqn__constraints.append(temp)
    for i in range(3):
        temp = "ASSERT %s = 0bin0;\n" % temp_1[i]
        eqn__constraints.append(temp)

    eqn__constraints.append(boolean_value(block_size, right_shift(in_var_w0, 17), right_shift(in_var_w0, 19), right_shift(in_var_w0, 10)[:22] + temp_0, in_var_b[0], "XOR"))

    eqn__constraints.append(boolean_value(block_size, right_shift(in_var_w2, 7), right_shift(in_var_w2, 18), right_shift(in_var_w2, 3)[:29] + temp_1, in_var_b[1], "XOR"))

    eqn__constraints.append(modadd_value(block_size, in_var_b[0], in_var_b[1], in_var_c[0], in_var_b[2]))

    eqn__constraints.append(modadd_value(block_size, in_var_b[2], in_var_w1, in_var_c[1], in_var_b[3]))

    eqn__constraints.append(modadd_value(block_size, in_var_b[3], in_var_w3, in_var_c[2], in_var_w4))

    return eqn__variable, eqn__constraints

def get_dc(block_size, data_list, var_str, step):
    result = []
    data = data_list.replace("ASSERT( ", "").replace(" );", "").replace("\nInvalid.", "").split("\n")
    xv = []
    xd = []
    x = []
    for i in range(step):
        temp_v = []
        temp_d = []
        temp = []
        for j in range(block_size):
            temp_v.append(0)
            temp_d.append(0)
            temp.append(0)
        xv.append(temp_v)
        xd.append(temp_d)
        x.append(temp)
    for i in data:
        if var_str + "v" in i:
            index, value = handle(i)
            xv[int(index[1])][int(index[2])] = value
        elif var_str + "d" in i:
            index, value = handle(i)
            xd[int(index[1])][int(index[2])] = value
    for i in range(len(xv)):
        for j in range(block_size):
            if xv[i][j] == "1" and xd[i][j] == "1":
                x[i][j] = "u"
            elif xv[i][j] == "0" and xd[i][j] == "0":
                x[i][j] = "0"
            elif xv[i][j] != xd[i][j]:
                x[i][j] = "n"

    for i in range(len(x)):
        temp = "%s\"" % i
        for j in range(block_size - 1, -1, -1):
            if x[i][j] == "0":
                temp += "="
            elif x[i][j] == "u":
                temp += "u"
            elif x[i][j] == "n":
                temp += "n"
        temp += "\","
        result.append(temp)
    return result


def handle(s):
    temp = s.replace("0b", "").split(" = ")
    index = temp[0].split("_")
    return index, temp[1]


def read_differential_characteristic(block_size, result_file, step):
    result = []
    print(result_file)
    data_list = open(result_file, "r").read()
    variable_list = ["x", "y", "w"]
    for var in variable_list:
        result.append(get_dc(block_size, data_list, var, step))
        result.append("")
    return result